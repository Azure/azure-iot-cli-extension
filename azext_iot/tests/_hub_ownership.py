# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Process-local ARM ownership observer. No inventory-diff ownership or sweeping deletes."""

import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import parse_qs, urlsplit

ARM = "https://centraluseuap.management.azure.com"
AUDIENCE = "https://management.azure.com/"
SUBSCRIPTION = "a386d5ea-ea90-441a-8263-d816368c84a1"
GROUP = "cli-int-test-rg"
REGION = "centraluseuap"
OWNER_TAG = "azextHubRunId"
ROOT_TYPES = {
    ("microsoft.devices", "iothubs"), ("microsoft.storage", "storageaccounts"),
    ("microsoft.managedidentity", "userassignedidentities"), ("microsoft.eventhub", "namespaces"),
    ("microsoft.servicebus", "namespaces"), ("microsoft.documentdb", "databaseaccounts"),
}
ROUTE_REJECTION_NODE = (
    "azext_iot/tests/iothub/message_endpoint/test_iothub_message_route_int.py::test_route_lifecycle"
)


def planned_root(resource_id):
    """Naming contracts from iothub/__init__, conftest and the state regressions."""
    parts = resource_id.casefold().split("/")
    if len(parts) != 9:
        return False
    patterns = {
        ("microsoft.devices", "iothubs"): r"(test-hub-[0-9a-f]{32}|aziotclitest-hub-[0-9a-f]{18})",
        ("microsoft.storage", "storageaccounts"): r"(hubstore[0-9a-f]{4}|aziotclitest[0-9a-f]{12})",
        ("microsoft.managedidentity", "userassignedidentities"): r"([0-9a-f]{32}|aziotclitest[0-9a-f]{12})",
        ("microsoft.eventhub", "namespaces"): r"aziotclitest[0-9a-f]{12}",
        ("microsoft.servicebus", "namespaces"): r"(sb[0-9a-f]{22}|aziotclitest[0-9a-f]{12})",
        ("microsoft.documentdb", "databaseaccounts"): r"(scos[0-9a-f]{32}|aziotclitest[0-9a-f]{12})",
    }
    return re.fullmatch(patterns.get((parts[-3], parts[-2]), r"(?!)"), parts[-1]) is not None


def literal_tree(value):
    """ARM expressions may create hidden targets or evaluate foreign references."""
    if isinstance(value, str):
        return not value.lstrip().startswith("[")
    if isinstance(value, dict):
        return all(literal_tree(key) and literal_tree(item) for key, item in value.items())
    if isinstance(value, list):
        return all(literal_tree(item) for item in value)
    return value is None or isinstance(value, (int, float, bool))


def expected_rejection(mutation):
    return (mutation.get("status") == 400 and mutation.get("method") == "PUT"
            and mutation.get("validation") == "missing-route-endpoint"
            and mutation.get("node") == ROUTE_REJECTION_NODE and bool(mutation.get("fingerprint")))


def pending_mutation(mutation):
    return (mutation.get("status") in (200, 201, 202)
            and (mutation["status"] == 202 or mutation.get("awaitingProvisioning"))
            and not mutation.get("reconciled"))


def request_body(raw):
    """Decode JSON or the CLI policy's single unquoted envelope template key.

    Only repair the exact JSON parser error position. Template contents remain
    strict JSON and still pass the literal deployment allowlist.
    """
    raw = raw or "{}"
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        if raw[error.pos:error.pos + 9] != "template:":
            raise OwnershipError("Invalid deployment JSON envelope") from error
        repaired = raw[:error.pos] + '"template":' + raw[error.pos + 9:]
        body = json.loads(repaired)
        props = body.get("properties", {})
        # Verify the exact splice produced by JsonCTemplatePolicy, not a
        # general JSON5 parser or a repair of arbitrary unquoted keys.
        template = props.get("template")
        prefix = raw[:error.pos]
        envelope = json.loads(prefix.rstrip()[:-1] + "}}")
        if (set(envelope) - {"properties", "location", "tags"}
                or "template" in envelope.get("properties", {})
                or not isinstance(template, dict)
                or props != dict(envelope.get("properties", {}), template=template)):
            raise OwnershipError("Invalid CLI deployment envelope")
        return body


def observe_get(data, resource_id, status, resource):
    """A GET can resolve acknowledged acceptance, never an unknown transport outcome."""
    for root, record in data["resources"].items():
        if resource_id == root and status == 404 and record["mutations"]:
            latest = record["mutations"][-1]
            if latest["id"] == root and latest["method"] == "DELETE" and latest["status"] in (200, 202, 204, 404):
                latest["absenceConfirmed"] = True
        if resource_id == root and status == 200:
            if (resource.get("id", "").casefold() != root
                    or resource.get("tags", {}).get(OWNER_TAG) != data["runId"]):
                raise OwnershipError("Observed resource no longer belongs to this phase")
            if record["mutations"][0]["status"] in (200, 201, 202):
                record["resolved"] = True
            if ("/microsoft.resources/deployments/" in root
                    and resource.get("properties", {}).get("provisioningState", "").casefold() == "succeeded"):
                record["deploymentSucceeded"] = True
        for mutation in record["mutations"]:
            if mutation["id"] != resource_id or not pending_mutation(mutation):
                continue
            if mutation["method"] == "DELETE":
                confirmed = status == 404
            else:
                state = resource.get("properties", {}).get("provisioningState", "") if status == 200 else ""
                deployed = mutation.get("deployment")
                deployment_done = not deployed or data["resources"][deployed].get("deploymentSucceeded")
                confirmed = (status == 200 and resource.get("id", "").casefold() == resource_id
                             and deployment_done
                             and (state.casefold() == "succeeded" or (deployed and "/certificates/" in resource_id)))
                if confirmed and "/microsoft.resources/deployments/" in resource_id:
                    record["deploymentSucceeded"] = True
            if confirmed:
                mutation["reconciled"] = True
        record["uncertain"] = any(
            m["status"] is None or pending_mutation(m)
            or m["status"] in (408, 429) or (isinstance(m["status"], int) and m["status"] >= 500)
            for m in record["mutations"]
        )


def reconcile(arm, data, deadline, save):
    """Bounded GET-only resolution of acknowledged provisioning, never ambiguity."""
    previous = arm.deadline
    arm.deadline = min(previous or float("inf"), deadline)
    try:
        _reconcile(arm, data, arm.deadline, save)
    finally:
        arm.deadline = previous


def _reconcile(arm, data, deadline, save):
    for record in data["resources"].values():
        if not record.get("uncertain"):
            continue
        mutations = record.get("mutations", [])
        if not mutations or any(
            m.get("status") is None or m.get("status") in (408, 429)
            or (isinstance(m.get("status"), int) and m["status"] >= 500) for m in mutations
        ):
            return

    def targets():
        pending = set()
        for record in data["resources"].values():
            for mutation in record["mutations"]:
                if not pending_mutation(mutation):
                    continue
                pending.add((mutation["id"], mutation.get("apiVersion", record["apiVersion"])))
                if mutation.get("deployment"):
                    deployment = mutation["deployment"]
                    pending.add((deployment, data["resources"][deployment]["apiVersion"]))
        return sorted(pending, key=lambda item: ("/microsoft.resources/deployments/" not in item[0], item[0]))

    pending = targets()
    while pending and time.monotonic() < deadline:
        for target, api in pending:
            if time.monotonic() >= deadline:
                break
            status, resource = arm.request("GET", target, api)
            observe_get(data, target, status, resource)
            save()
        pending = targets()
        if pending:
            time.sleep(min(1, max(0, deadline - time.monotonic())))


class OwnershipError(RuntimeError):
    """Ownership or mutation outcome is not proven."""


def scope_id(resource_id):
    prefix = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{GROUP}/providers/"
    return (isinstance(resource_id, str) and resource_id.casefold().startswith(prefix.casefold())
            and len(resource_id.split("/")) >= 9
            and all(re.fullmatch(r"[A-Za-z0-9_.()-]+", part) and part not in (".", "..")
                    for part in resource_id.split("/")[1:]))


def write(path, data):
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        json.dump(data, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def ownership_errors(data, run_id, phase):
    errors = []
    if (data.get("schemaVersion") != 1 or data.get("runId") != run_id
            or data.get("phase") != phase or not data.get("installed")):
        errors.append("missing/mismatched observer receipt")
    records = data.get("resources", {})
    if not records:
        errors.append("no pre-create resource receipts")
    for resource_id, record in records.items():
        history = record.get("generations", [])
        if record.get("generation", 1) != len(history) + 1:
            errors.append("invalid generation chain")
        for index, previous in enumerate(history):
            prior = dict(data, resources={resource_id: previous}, violations=[])
            errors.extend(ownership_errors(prior, run_id, phase))
            mutations = previous.get("mutations", [])
            if (previous.get("generation", 1) != index + 1 or not mutations
                    or mutations[-1].get("method") != "DELETE"
                    or mutations[-1].get("id") != resource_id
                    or not mutations[-1].get("absenceConfirmed")):
                errors.append("unconfirmed previous generation deletion")
        if (not scope_id(resource_id) or record.get("id") != resource_id
                or record.get("before") != 404 or not record.get("apiVersion")
                or not record.get("attempted") or record.get("ownerTag") != run_id):
            errors.append("invalid pre-create evidence")
        if record.get("uncertain") or not record.get("resolved"):
            errors.append("unresolved mutation; no replay permitted")
        mutations = record.get("mutations", [])
        if not mutations or mutations[0].get("method") != "PUT":
            errors.append("missing initial mutation")
        if any(m.get("status") not in (200, 201, 202, 204, 404) and not expected_rejection(m) for m in mutations):
            errors.append("missing/failed mutation response")
        if any(pending_mutation(m) for m in mutations):
            errors.append("unreconciled asynchronous acceptance")
        for mutation in mutations:
            target = mutation.get("id", "")
            if (not scope_id(target) or not (target == resource_id or target.startswith(resource_id + "/"))
                    or mutation.get("method") not in ("PUT", "PATCH", "DELETE", "POST")
                    or (target != resource_id and not mutation.get("apiVersion"))
                    or (mutation.get("status") == 404 and mutation.get("method") != "DELETE")):
                errors.append("mutation outside owned resource tree")
            if expected_rejection(mutation) and (target != resource_id or mutation is mutations[0]):
                errors.append("invalid expected validation rejection")
            if mutation.get("method") == "POST" and (
                mutation.get("action") not in ("generateverificationcode", "verify")
                or re.search(r"/microsoft.devices/iothubs/[^/]+/certificates/[^/]+$", target) is None
            ):
                errors.append("unplanned owned ARM action")
    if data.get("violations"):
        errors.append("ownership boundary violation")
    return errors


def descendants(data):
    """Only exact ARM paths observed below proven owned roots, not inventory discoveries."""
    return {
        mutation["id"]: mutation["apiVersion"]
        for resource_id, record in data["resources"].items() for mutation in record["mutations"]
        if mutation["id"] != resource_id
    }


class Arm:
    """Explicit Profile tokens, no EmbeddedCLI token retrieval, no mutation retries."""

    def __init__(self):
        import requests
        from azure.cli.core import get_default_cli
        from azure.cli.core._profile import Profile
        self.profile = Profile(cli_ctx=get_default_cli())
        self.session = requests.Session()
        self.deadline = None

    def request(self, method, resource_id, api):
        from azext_iot.tests._dps_phase_runner import bounded_read
        if method not in ("GET", "DELETE") or not scope_id(resource_id):
            raise OwnershipError("ARM scope rejected")
        with bounded_read(self.deadline):
            token, _, _ = self.profile.get_raw_token(subscription=SUBSCRIPTION, resource=AUDIENCE)
            response = self.session.request(
                method, ARM + resource_id, params={"api-version": api},
                headers={"Authorization": "Bearer " + token[1]}, timeout=(5, 20), allow_redirects=False,
            )
            if response.status_code not in (200, 201, 202, 204, 404):
                raise OwnershipError("ARM request failed (response omitted)")
            return response.status_code, response.json() if response.status_code == 200 else None

    def inventory(self):
        from azext_iot.tests._dps_phase_runner import bounded_read
        from azext_iot._factory import _ADR_IOT_HUB_API_VERSION
        url = ARM + f"/subscriptions/{SUBSCRIPTION}/providers/Microsoft.Devices/IotHubs"
        resources, seen = [], set()
        with bounded_read(self.deadline):
            token, _, _ = self.profile.get_raw_token(subscription=SUBSCRIPTION, resource=AUDIENCE)
            while url:
                parsed = urlsplit(url)
                if (parsed.scheme != "https" or parsed.netloc != urlsplit(ARM).netloc
                        or not parsed.path.casefold().startswith(f"/subscriptions/{SUBSCRIPTION}/".casefold())
                        or url in seen):
                    raise OwnershipError("Invalid Hub inventory continuation")
                seen.add(url)
                response = self.session.get(
                    url, params=None if parsed.query else {"api-version": _ADR_IOT_HUB_API_VERSION},
                    headers={"Authorization": "Bearer " + token[1]}, timeout=(5, 20), allow_redirects=False,
                )
                if response.status_code != 200:
                    raise OwnershipError("Subscription Hub inventory unavailable")
                body = response.json()
                if not isinstance(body.get("value"), list):
                    raise OwnershipError("Incomplete Hub inventory")
                resources.extend(item["id"] for item in body["value"])
                url = body.get("nextLink")
        if len(set(value.casefold() for value in resources)) != len(resources):
            raise OwnershipError("Duplicate Hub inventory IDs")
        return resources


class Observer:
    """Installed before conftest imports; only new fixture roots in the authorized RG.

    A durable record precedes every initial PUT. Subsequent operations are permitted
    only below these roots. An ambiguous response permanently poisons the record:
    neither a SDK retry nor controller cleanup may replay it.
    """

    def __init__(self, path, run_id, phase, arm):
        self.path, self.arm = Path(path), arm
        self.lock = threading.RLock()
        self.data = {
            "schemaVersion": 1, "runId": run_id, "phase": phase,
            "installed": False, "resources": {}, "violations": [],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("x", encoding="utf-8"):
            pass
        self.original_send = self.original_subscription = None
        self.current_node = None
        self.deployment_plans = set()
        self.save()

    def save(self):
        write(self.path, self.data)

    def reject(self, reason):
        self.data["violations"].append(reason)
        self.save()
        raise OwnershipError(reason)

    def prepare(self, method, resource_id, api, body):
        """Return the owning root; called under the transport lock before send."""
        resource_id = resource_id.casefold()
        if not scope_id(resource_id) or not api:
            self.reject("Mutation outside explicit resource scope")
        if body.get("tags") is not None and not isinstance(body["tags"], dict):
            self.reject("Invalid resource tags")
        roots = self.data["resources"]
        root = next((key for key in roots if resource_id == key or resource_id.startswith(key + "/")), None)
        if root is None:
            parts = resource_id.split("/")
            # /subscriptions/S/resourceGroups/G/providers/NS/type/name
            if method != "PUT" or not (planned_root(resource_id) or resource_id in self.deployment_plans):
                self.reject("Mutation has no owned fixture root")
            if body.get("location", REGION).casefold() != REGION:
                self.reject("Resource location outside authorized region")
            if parts[-2] == "iothubs" and body.get("properties", {}).get("disableLocalAuth") is not True:
                self.reject("Ordinary Hub must disable local authentication")
            if parts[-2] == "iothubs" and len(self.arm.inventory()) >= 50:
                self.reject("No subscription Hub capacity remains at creation")
            status, _ = self.arm.request("GET", resource_id, api)
            if status != 404:
                self.reject("Cannot own a pre-existing resource")
            root = resource_id
            roots[root] = {
                "id": root, "apiVersion": api, "before": 404,
                "ownerTag": self.data["runId"],
                "attempted": True, "resolved": False, "uncertain": True, "mutations": [],
            }
        else:
            if roots[root]["uncertain"]:
                deadline = min(self.arm.deadline or float("inf"), time.monotonic() + 60)
                reconcile(self.arm, self.data, deadline, self.save)
            if roots[root]["uncertain"]:
                self.reject("Uncertain mutation cannot be replayed")
            if not roots[root]["resolved"]:
                self.reject("Failed initial creation cannot authorize an update")
            if roots[root]["resolved"]:
                status, resource = self.arm.request("GET", root, roots[root]["apiVersion"])
                if status == 404 and method != "DELETE":
                    observe_get(self.data, root, status, resource)
                    latest = roots[root]["mutations"][-1]
                    if (method != "PUT" or resource_id != root or not planned_root(root)
                            or latest["method"] != "DELETE" or not latest.get("absenceConfirmed")
                            or latest["status"] not in (200, 202, 204, 404)):
                        self.reject("Owned update target disappeared")
                    if (body.get("location", REGION).casefold() != REGION
                            or ("/iothubs/" in root and body.get("properties", {}).get("disableLocalAuth") is not True)):
                        self.reject("Invalid recreation location/auth")
                    if "/iothubs/" in root and len(self.arm.inventory()) >= 50:
                        self.reject("No subscription Hub capacity remains at creation")
                    previous = roots[root]
                    roots[root] = dict(previous, mutations=[], resolved=False, uncertain=False,
                                       generation=previous.get("generation", 1) + 1,
                                       generations=previous.get("generations", []) + [previous])
                if status != 404 and (
                    resource.get("id", "").casefold() != root
                    or resource.get("tags", {}).get(OWNER_TAG) != self.data["runId"]
                ):
                    self.reject("Delete target no longer has this phase's ownership tag")
            if method in ("PUT", "PATCH") and root == resource_id and "/iothubs/" in root:
                if body.get("properties", {}).get("disableLocalAuth") is False:
                    self.reject("Ordinary Hub cannot enable local authentication")
        canonical = dict(body)
        if "tags" in canonical:
            tags = {key: value for key, value in (canonical["tags"] or {}).items() if key != OWNER_TAG}
            if tags:
                canonical["tags"] = tags
            else:
                del canonical["tags"]
        fingerprint = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
        if any(m.get("fingerprint") == fingerprint and m["method"] == method and m["id"] == resource_id
               and (m.get("status") == 400 or pending_mutation(m)) for m in roots[root]["mutations"]):
            self.reject("Rejected or accepted asynchronous operation cannot be replayed")
        mutation = {"method": method, "id": resource_id, "apiVersion": api, "status": None,
                    "fingerprint": fingerprint, "node": self.current_node}
        if (root == resource_id and roots[root]["resolved"] and method == "PUT"
                and "/iothubs/" in root and self.current_node == ROUTE_REJECTION_NODE):
            routing = body.get("properties", {}).get("routing", {})
            endpoints = {"events"} | {ep["name"] for group in routing.get("endpoints", {}).values() for ep in group}
            if any(re.fullmatch(r"ep[0-9a-f]{32}", name) and name not in endpoints
                   for route in routing.get("routes", []) for name in route.get("endpointNames", [])):
                mutation["validation"] = "missing-route-endpoint"
        roots[root]["uncertain"] = True
        roots[root]["mutations"].append(mutation)
        self.save()
        return root

    def validate_deployment(self, resource_id, body):
        """Only state.py's literal single-Hub + certificates and blank_hub_arm forms.

        No linked/nested templates, expression-based names, complete-mode sweeps,
        extension resources, scripts, copy loops, parameters or arbitrary targets.
        """
        props = body.get("properties", {})
        template = props.get("template", {})
        if (self.data["phase"] != "regular" or not scope_id(resource_id)
                or len(resource_id.split("/")) != 9 or "/microsoft.resources/deployments/" not in resource_id
                or set(body) - {"properties", "tags", "location"}
                or set(props) - {"template", "parameters", "mode", "validationLevel"}
                or props.get("mode", "").casefold() != "incremental" or props.get("parameters")
                or not isinstance(template, dict)
                or set(template) - {"$schema", "contentVersion", "parameters", "variables", "resources", "outputs"}
                or any(template.get(key) for key in ("parameters", "variables", "outputs"))):
            self.reject("Unplanned deployment envelope")
        resources = template.get("resources", [])
        if not isinstance(resources, list) or not resources:
            self.reject("Missing literal state deployment resources")
        hub = resources[0]
        if not isinstance(hub, dict) or hub.get("type", "").casefold() != "microsoft.devices/iothubs":
            self.reject("State deployment must start with exactly one Hub")
        prefix = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{GROUP}/providers/".casefold()
        hub_id = prefix + "microsoft.devices/iothubs/" + hub.get("name", "").casefold()
        name = resource_id.rsplit("/", 1)[1]
        if (not scope_id(hub_id) or not planned_root(hub_id)
                or not (name == "arm_deployment-" + hub["name"].casefold() or re.fullmatch(r"[0-9a-f]{32}", name))
                or hub.get("location", "").casefold() != REGION
                or hub.get("properties", {}).get("disableLocalAuth") is not True):
            self.reject("Unplanned state deployment Hub/name/location/auth")
        targets = []
        for index, resource in enumerate(resources):
            if (not isinstance(resource, dict)
                    or set(resource) - {"type", "apiVersion", "name", "location", "properties", "sku", "identity",
                                        "tags", "dependsOn"}):
                self.reject("Unplanned deployment resource fields")
            resource_type = resource.get("type", "").casefold()
            target = prefix + resource_type + "/" + resource.get("name", "").casefold()
            if index:
                if (resource_type != "microsoft.devices/iothubs/certificates"
                        or not re.fullmatch(re.escape(hub["name"]) + r"/[A-Za-z0-9_.()-]+", resource.get("name", ""))):
                    self.reject("Only this Hub's literal certificates may follow it")
                target = hub_id + "/certificates/" + resource["name"].split("/")[1].casefold()
                dependencies = resource.get("dependsOn", [])
                if dependencies != [f"[resourceId('Microsoft.Devices/IotHubs', '{hub['name']}')]"]:
                    self.reject("Unexpected state certificate dependency")
            elif resource.get("dependsOn"):
                self.reject("Unexpected Hub dependency expression")
            if not resource.get("apiVersion") or not literal_tree({k: v for k, v in resource.items() if k != "dependsOn"}):
                self.reject("Nonliteral state deployment")
            targets.append((target, resource))
        if len({target for target, _ in targets}) != len(targets):
            self.reject("Duplicate deployment targets")
        # Identity references in both the Hub and routing settings must be owned.

        def references(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key.casefold().startswith("/subscriptions/"):
                        self.require_owned_reference(key, "microsoft.managedidentity/userassignedidentities")
                    if key == "userAssignedIdentity" and item:
                        self.require_owned_reference(item, "microsoft.managedidentity/userassignedidentities")
                    if key == "subscriptionId" and item.casefold() != SUBSCRIPTION:
                        self.reject("Foreign deployment subscription reference")
                    if key == "resourceGroup" and item.casefold() != GROUP:
                        self.reject("Foreign deployment resource-group reference")
                    if key == "endpointUri" and item:
                        self.require_owned_endpoint(urlsplit(item).hostname)
                    if key == "connectionString" and item:
                        fields = dict(part.split("=", 1) for part in item.split(";") if "=" in part)
                        if fields.get("AccountName"):
                            self.require_owned_endpoint(fields["AccountName"] + ".blob.core.windows.net")
                        elif fields.get("Endpoint") or fields.get("AccountEndpoint"):
                            self.require_owned_endpoint(urlsplit(fields.get("Endpoint") or fields["AccountEndpoint"]).hostname)
                        else:
                            self.reject("Unrecognized deployment endpoint connection string")
                    references(item)
            elif isinstance(value, list):
                for item in value:
                    references(item)
        references(hub)
        if hub_id not in self.data["resources"] and any(
            endpoint.get("authenticationType") == "identityBased"
            and not endpoint.get("identity", {}).get("userAssignedIdentity")
            for endpoints in hub.get("properties", {}).get("routing", {}).get("endpoints", {}).values()
            for endpoint in endpoints
        ):
            self.reject("New state destinations cannot use source system-identity endpoints")
        return targets

    def require_owned_reference(self, resource_id, resource_type):
        target = resource_id.casefold()
        record = self.data["resources"].get(target, {})
        if (not scope_id(target) or f"/providers/{resource_type}/" not in target
                or not record.get("resolved") or record.get("uncertain")):
            self.reject("Deployment references an unowned identity")
        status, resource = self.arm.request("GET", target, record["apiVersion"])
        if (status != 200 or resource.get("id", "").casefold() != target
                or resource.get("tags", {}).get(OWNER_TAG) != self.data["runId"]):
            self.reject("Deployment reference ownership changed")

    def require_owned_endpoint(self, hostname):
        suffixes = {
            "microsoft.eventhub/namespaces": ".servicebus.windows.net",
            "microsoft.servicebus/namespaces": ".servicebus.windows.net",
            "microsoft.documentdb/databaseaccounts": ".documents.azure.com",
            "microsoft.storage/storageaccounts": ".blob.core.windows.net",
        }
        for root in self.data["resources"]:
            for kind, suffix in suffixes.items():
                if f"/providers/{kind}/" in root and hostname == root.rsplit("/", 1)[1] + suffix:
                    self.require_owned_reference(root, kind)
                    return
        self.reject("Deployment references an unowned routing/storage endpoint")

    def prepare_deployment(self, resource_id, api, body):
        targets = self.validate_deployment(resource_id, body)
        if not api:
            self.reject("Missing deployment API version")
        status, current = self.arm.request("GET", resource_id, api)
        if status != 404 and (
            resource_id not in self.data["resources"] or current.get("id", "").casefold() != resource_id
            or current.get("tags", {}).get(OWNER_TAG) != self.data["runId"]
        ):
            self.reject("Cannot own a pre-existing deployment")
        if resource_id in self.data["resources"]:
            self.reject("Deployment cannot be replayed")
        # ARM cannot conditionalize template targets. Only literal fixture IDs
        # with fresh exact absence receipts may be created by this single submit.
        hub_id, hub = targets[0]
        before = {}
        for target, resource in targets:
            target_status, _ = self.arm.request("GET", target, resource["apiVersion"])
            if target_status != 404 and hub_id not in self.data["resources"]:
                self.reject("Cannot own a pre-existing deployment target")
            before[target] = target_status
        root = self.prepare("PUT", hub_id, hub["apiVersion"], hub)
        self.deployment_plans.add(resource_id)
        deployment = self.prepare("PUT", resource_id, api, body)
        self.data["resources"][deployment]["deploymentSucceeded"] = False
        self.data["resources"][deployment]["deploymentTargets"] = [target for target, _ in targets]
        mutations = self.data["resources"][root]["mutations"]
        mutations[-1]["deployment"] = deployment
        mutations[-1]["before"] = before[hub_id]
        for target, resource in targets[1:]:
            mutations.append({"method": "PUT", "id": target, "apiVersion": resource["apiVersion"],
                              "status": None, "deployment": deployment, "before": before[target]})
        hub["tags"] = dict(hub.get("tags") or {}, **{OWNER_TAG: self.data["runId"]})
        self.save()
        return deployment, root, len(targets)

    def complete(self, root, status):
        record = self.data["resources"][root]
        record["mutations"][-1]["status"] = status
        record["uncertain"] = status == 202 or status in (408, 429) or status >= 500
        if status == 404 and record["mutations"][-1]["method"] == "DELETE":
            record["uncertain"] = False
        # 202 is an unresolved acceptance until an exact resource GET observes it.
        if record["mutations"][-1]["method"] == "PUT" and status in (200, 201):
            record["resolved"] = True
        self.save()

    def install(self):
        import requests
        from azure.cli.core._profile import Profile
        from urllib3.util.retry import Retry
        owner = self
        self.original_send = requests.Session.send
        self.original_subscription = Profile.get_subscription

        def subscription(profile, subscription=None):
            if subscription and subscription.casefold() != SUBSCRIPTION:
                raise OwnershipError("Foreign subscription override")
            return owner.original_subscription(profile, SUBSCRIPTION)

        def send(session, request, **kwargs):
            parsed = urlsplit(request.url)
            is_arm = parsed.hostname in ("management.azure.com", urlsplit(ARM).hostname)
            if not is_arm:
                return owner.original_send(session, request, **kwargs)
            # Change only this process's ARM request destination, not Azure cloud defaults.
            request.url = ARM + parsed.path + ("?" + parsed.query if parsed.query else "")
            method, resource_id = request.method, parsed.path.rstrip("/").casefold()
            with owner.lock:
                body = request_body(request.body) if method in ("PUT", "PATCH", "POST") else {}
                api = parse_qs(parsed.query).get("api-version", [None])[0]
                action = resource_id.rsplit("/", 1)[-1]
                action_root = resource_id.rsplit("/", 1)[0]
                readonly = False
                if method == "POST" and action == "exporttemplate":
                    group_id = f"/subscriptions/{SUBSCRIPTION}/resourcegroups/{GROUP}"
                    resources = body.get("resources", [])
                    if (resource_id != group_id + "/exporttemplate" or set(body) - {"resources", "options"}
                            or not resources or not isinstance(resources, list)
                            or body.get("options", "").casefold() not in ("", "skipallparameterization")
                            or any(not isinstance(value, str) or value.casefold() not in owner.data["resources"]
                                   or not owner.data["resources"][value.casefold()]["resolved"]
                                   or owner.data["resources"][value.casefold()]["uncertain"] for value in resources)):
                        owner.reject("Export requires an exact owned resource subset")
                    readonly = True
                if method == "POST" and action in ("testroute", "testallroutes"):
                    if (action_root not in owner.data["resources"] or "/microsoft.devices/iothubs/" not in action_root
                            or not owner.data["resources"][action_root]["resolved"]
                            or owner.data["resources"][action_root]["uncertain"]):
                        owner.reject("Route testing requires an exact owned Hub")
                    readonly = True
                if method == "POST" and action == "validate" and "/microsoft.resources/deployments/" in action_root:
                    owner.validate_deployment(action_root, body)
                    readonly = True
                certificate_action = (
                    method == "POST" and re.search(
                        r"/microsoft.devices/iothubs/[^/]+/certificates/[^/]+/(generateverificationcode|verify)$",
                        resource_id,
                    ) is not None
                )
                if method == "POST" and not resource_id.endswith((
                    "/listkeys", "/listconnectionstrings", "/checknameavailability",
                )) and not certificate_action and not readonly:
                    owner.reject("Unplanned ARM action")
                root = None
                deployed = None
                if method in ("PUT", "PATCH", "DELETE") or certificate_action:
                    target = resource_id.rsplit("/", 1)[0] if certificate_action else resource_id
                    if method == "PUT" and "/microsoft.resources/deployments/" in resource_id:
                        root, hub_root, count = owner.prepare_deployment(resource_id, api, body)
                        deployed = hub_root, count
                    else:
                        root = owner.prepare(method, target, api, body)
                    if certificate_action:
                        owner.data["resources"][root]["mutations"][-1]["action"] = resource_id.rsplit("/", 1)[1]
                        owner.save()
                    if len(owner.data["resources"][root]["mutations"]) == 1:
                        request.headers["If-None-Match"] = "*"
                    if method in ("PUT", "PATCH") and resource_id == root:
                        body["tags"] = dict(body.get("tags") or {}, **{OWNER_TAG: owner.data["runId"]})
                        request.prepare_body(data=json.dumps(body), files=None)
                    session.get_adapter(request.url).max_retries = Retry(total=0, redirect=0)
                # Preserve SDK mutation acknowledgement timeouts; pytest/phase
                # absolute deadlines remain authoritative.
                kwargs.setdefault("timeout", (5, 60))
                kwargs["allow_redirects"] = False
                try:
                    response = owner.original_send(session, request, **kwargs)
                except requests.RequestException as error:
                    if root:
                        owner.data["resources"][root]["mutations"][-1]["transportError"] = type(error).__name__
                        owner.save()
                    raise
                if root:
                    owner.complete(root, response.status_code)
                if deployed:
                    hub_root, count = deployed
                    for mutation in owner.data["resources"][hub_root]["mutations"][-count:]:
                        # A deployment response does not prove any individual target.
                        mutation["status"] = 202 if 200 <= response.status_code < 300 else response.status_code
                    owner.save()
                if method == "GET":
                    try:
                        observe_get(owner.data, resource_id, response.status_code,
                                    response.json() if response.status_code == 200 else None)
                    except OwnershipError:
                        owner.reject("Observed resource no longer belongs to this phase")
                    owner.save()
                return response

        requests.Session.send = send
        Profile.get_subscription = subscription
        self.data["installed"] = True
        self.save()

    def restore(self):
        if self.original_send is not None:
            import requests
            from azure.cli.core._profile import Profile
            requests.Session.send = self.original_send
            Profile.get_subscription = self.original_subscription


class ProcessScope:
    """Subscription/token scope and canary endpoint, in memory only, also for SAS."""

    def install(self):
        import requests
        from azure.cli.core._profile import Profile
        self.send = requests.Session.send
        self.subscription = Profile.get_subscription
        self.token = Profile.get_raw_token
        scope = self

        def subscription(profile, subscription=None):
            if subscription and subscription.casefold() != SUBSCRIPTION:
                raise OwnershipError("Foreign subscription override")
            return scope.subscription(profile, SUBSCRIPTION)

        def token(profile, resource=None, scopes=None, subscription=None, *args, **kwargs):
            if subscription and subscription.casefold() != SUBSCRIPTION:
                raise OwnershipError("Foreign token subscription override")
            arm_hosts = {"management.azure.com", "management.core.windows.net", urlsplit(ARM).hostname}
            if scopes and all(urlsplit(value).hostname in arm_hosts for value in scopes):
                resource, scopes = None, [AUDIENCE + ".default"]
            elif not scopes and (resource is None or urlsplit(resource).hostname in arm_hosts):
                resource = AUDIENCE
            return scope.token(profile, resource=resource, scopes=scopes, subscription=SUBSCRIPTION, *args, **kwargs)

        def send(session, request, **kwargs):
            parsed = urlsplit(request.url)
            if parsed.path.casefold().startswith("/subscriptions/") and parsed.hostname not in (
                "management.azure.com", urlsplit(ARM).hostname,
            ):
                raise OwnershipError("Unapproved ARM endpoint")
            if parsed.hostname in ("management.azure.com", urlsplit(ARM).hostname):
                request.url = ARM + parsed.path + ("?" + parsed.query if parsed.query else "")
                kwargs["allow_redirects"] = False
            return scope.send(session, request, **kwargs)

        requests.Session.send = send
        Profile.get_subscription = subscription
        Profile.get_raw_token = token

    def restore(self):
        import requests
        from azure.cli.core._profile import Profile
        requests.Session.send = self.send
        Profile.get_subscription = self.subscription
        Profile.get_raw_token = self.token
