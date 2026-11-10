# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Attempt-local ARM ownership for live tests in pre-created resource groups."""

import argparse
import hashlib
from itertools import groupby
import json
import os
from pathlib import Path
import re
import runpy
import sys
import time
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4


ENV = "AZEXT_TEST_OWNERSHIP"
TAG = "cliTestOwner"
PARAMETER = "cliTestOwner"
CLOUDS = {
    "AzureCloud": "https://management.azure.com",
    "AzureUSGovernment": "https://management.usgovcloudapi.net",
    "AzureChinaCloud": "https://management.chinacloudapi.cn",
}
ROLE_TYPE = "microsoft.authorization/roleassignments"
DEPLOYMENT_TYPE = "microsoft.resources/deployments"
API = re.compile(r"20\d{2}-\d{2}-\d{2}(?:-preview)?")
TERMINAL_STATES = {"succeeded", "failed", "canceled", "cancelled"}


def cloud_endpoints(cloud):
    result = {CLOUDS[cloud]}
    if cloud == "AzureCloud":
        result.add("https://centraluseuap.management.azure.com")
    return result


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def publish(path, content, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".pending-" + uuid4().hex)
    try:
        with temporary.open("xb") as stream:
            temporary.chmod(mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # Readers must never see a partially written event from another pytest worker.
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_new(path, value):
    publish(path, json.dumps(value, sort_keys=True).encode("utf-8"))


def new_context(**identity):
    value = {"schema": 1, "nonce": uuid4().hex, **identity}
    value["owner"] = digest(value)
    validate_context(value)
    return value


def create_context(path, **identity):
    value = new_context(**identity)
    write_new(path, value)
    return value


def validate_context(value):
    if (value.get("schema") != 1
            or value.get("owner") != digest({key: item for key, item in value.items() if key != "owner"})
            or value.get("cloud") not in CLOUDS
            or not re.fullmatch(r"[0-9a-f]{32}", value.get("nonce", ""))
            or not re.fullmatch(r"[0-9a-fA-F-]{36}", value.get("subscription", ""))
            or not re.fullmatch(r"[A-Za-z0-9_().-]{1,90}", value.get("resourceGroup", ""))):
        raise ValueError("Invalid live-resource ownership context.")
    if value.get("endpoint", CLOUDS[value["cloud"]]) not in cloud_endpoints(value["cloud"]):
        raise ValueError("Ownership endpoint does not belong to the configured cloud.")


class Journal:
    def __init__(self, path):
        self.path = Path(path).resolve()
        document = json.loads(self.path.read_text(encoding="utf-8"))
        self.context = document.get("ownership", document)
        validate_context(self.context)
        self.owner = self.context["owner"]
        self.group = (
            f"/subscriptions/{self.context['subscription']}/resourceGroups/{self.context['resourceGroup']}"
        ).lower()
        self.directory = self.path.with_suffix(".events")
        self._events = {}

    def resource_id(self, value):
        if not isinstance(value, str) or not re.fullmatch(r"/[A-Za-z0-9_.()-]+(?:/[A-Za-z0-9_.()-]+)*", value):
            raise ValueError("Invalid owned ARM resource ID.")
        value = value.lower()
        parts = value.split("/")
        if (not value.startswith(self.group + "/providers/") or len(parts) < 9
                or any(part in (".", "..") for part in parts)):
            raise ValueError("Resource is outside the attempt's fixed resource group.")
        return value

    def records(self):
        result = {}
        for path in sorted(self.directory.glob("*.json")):
            if path not in self._events:
                self._events[path] = json.loads(path.read_text(encoding="utf-8"))
            event = self._events[path]
            resource = self.resource_id(event["id"])
            if event.get("owner") != self.owner or not API.fullmatch(event.get("api", "")):
                raise ValueError("Resource journal belongs to another attempt or has an invalid API.")
            prior = result.setdefault(resource, {})
            evidence = {
                name: max(prior.get(name + "Ns", 0), event["timeNs"] if event.get(name) else 0)
                for name in ("confirmed", "settled")
            }
            creates = {**prior.get("creates", {}), **event.get("creates", {})}
            create_times = dict(prior.get("createTimes", {}))
            for creation in event.get("creates", {}):
                create_times.setdefault(creation, event["timeNs"])
            deployments = {**prior.get("deployments", {}), **event.get("deployments", {})}
            prior.update(event)
            if creates:
                prior["creates"] = creates
                prior["createTimes"] = create_times
            if deployments:
                prior["deployments"] = deployments
            for name, stamp in evidence.items():
                if stamp:
                    prior[name] = True
                    prior[name + "Ns"] = stamp
        return result

    def record(self, resource, api, **metadata):
        resource = self.resource_id(resource)
        if not API.fullmatch(api or ""):
            raise ValueError("An exact ARM API version is required for ownership evidence.")
        prior = self.records().get(resource, {})
        changes = {key: value for key, value in metadata.items() if key not in prior or prior[key] != value}
        for name in ("confirmed", "settled"):
            if metadata.get(name) and any(
                    stamp >= prior.get(name + "Ns", 0) for stamp in prior.get("createTimes", {}).values()):
                changes[name] = True
        if prior and not changes and prior["api"] == api:
            return prior
        event = {
            **changes, "owner": self.owner, "id": resource, "api": api,
            "timeNs": time.time_ns(),
        }
        write_new(self.directory / f"{event['timeNs']:020d}-{uuid4().hex}.json", event)
        return {**prior, **event}

    def violation(self, method, resource, error):
        write_new(self.path.with_suffix(".violations") / f"{uuid4().hex}.json", {
            "owner": self.owner, "method": method, "resource": resource, "errorType": type(error).__name__,
        })

    def has_violations(self):
        return any(self.path.with_suffix(".violations").glob("*.json"))

    @property
    def role_prefix(self):
        return f"{TAG}={self.owner}\n"

    def owns(self, resource):
        resource_id = resource.get("id", "")
        if not isinstance(resource_id, str) or not resource_id.lower().startswith(self.group + "/providers/"):
            return False
        kind = resource_type(resource_id)
        if kind == ROLE_TYPE:
            matches = (resource.get("properties", {}).get("description") or "").startswith(self.role_prefix)
        elif kind == DEPLOYMENT_TYPE:
            matches = resource.get("properties", {}).get("parameters", {}).get(PARAMETER, {}).get("value") == self.owner
        else:
            matches = (resource.get("tags") or {}).get(TAG) == self.owner
        if matches:
            self.resource_id(resource_id)
        return matches


def resource_type(resource):
    parts = resource.lower().rsplit("/providers/", 1)[1].split("/")
    return "/".join((parts[0], *parts[1::2]))


def creation_settled(resource, status=200):
    state = (resource.get("properties", {}).get("provisioningState") or "").lower()
    return status in (200, 201) and (not state or state in TERMINAL_STATES)


def request_body(raw):
    """Accept strict JSON or the CLI's exact unquoted deployment-template envelope."""
    raw = raw or "{}"
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        if raw[error.pos:error.pos + 9] != "template:":
            raise ValueError("Invalid deployment JSON envelope.") from error
        body = json.loads(raw[:error.pos] + '"template":' + raw[error.pos + 9:])
        properties = body.get("properties", {})
        template = properties.get("template")
        envelope = json.loads(raw[:error.pos].rstrip()[:-1] + "}}")
        if (set(envelope) - {"properties", "location", "tags"}
                or "template" in envelope.get("properties", {})
                or not isinstance(template, dict)
                or properties != dict(envelope.get("properties", {}), template=template)):
            raise ValueError("Invalid CLI deployment envelope.")
        return body


class Arm:
    def __init__(self, journal):
        import requests
        from azure.cli.core import get_default_cli
        from azure.cli.core._profile import Profile

        self.journal = journal
        cli = get_default_cli()
        if cli.cloud.name != journal.context["cloud"]:
            raise ValueError("Active Azure cloud differs from the ownership context.")
        self.endpoint = journal.context.get("endpoint", CLOUDS[cli.cloud.name])
        self.audience = cli.cloud.endpoints.active_directory_resource_id
        self.profile = Profile(cli_ctx=cli)
        self.session = requests.Session()
        self.deadline = None
        # Ownership reads must bypass the observer and retain the real Azure tags.
        self.session.send = self.session.send

    def timeout(self, deadline):
        remaining = min(self.deadline if self.deadline is not None else deadline, deadline) - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("ARM ownership budget expired.")
        connect = min(5, remaining / 2)
        return connect, min(25, remaining - connect)

    def send(self, method, url, *, headers=None, **kwargs):
        import requests
        from urllib3.util.retry import Retry

        deadline = min(
            self.deadline if self.deadline is not None else float("inf"),
            time.monotonic() + (90 if method == "GET" else 30),
        )
        token, _, _ = self.profile.get_raw_token(
            subscription=self.journal.context["subscription"], resource=self.audience,
        )
        for attempt in range(3):
            try:
                response = self.session.request(
                    method, url, headers={"Authorization": "Bearer " + token[1], **(headers or {})},
                    timeout=self.timeout(deadline), allow_redirects=False, **kwargs,
                )
            except requests.exceptions.SSLError:
                raise
            except (requests.ConnectionError, requests.Timeout):
                if method != "GET" or attempt == 2:
                    raise
                delay = 2 ** attempt
            else:
                if method != "GET" or response.status_code not in (408, 429, 500, 502, 503, 504) or attempt == 2:
                    return response
                delay = Retry().get_retry_after(response)
                if delay is None:
                    delay = 2 ** attempt
            if time.monotonic() + delay >= deadline:
                raise TimeoutError("ARM ownership retry exceeds its bounded read budget.")
            print(f"Retrying an ownership GET after a transient failure in {delay}s.", file=sys.stderr, flush=True)
            time.sleep(delay)
        raise RuntimeError("Ownership read retries were exhausted.")

    def request(self, method, resource, api, body=None, headers=None, query=None):
        response = self.send(
            method, self.endpoint + resource, params={"api-version": api} if query is None else query,
            json=body, headers=headers,
        )
        if response.status_code not in (200, 201, 202, 204, 404):
            raise RuntimeError(f"Ownership {method} failed with HTTP {response.status_code}; response body omitted.")
        if response.status_code == 404:
            try:
                error = response.json()
            except ValueError as exception:
                raise RuntimeError("Unverifiable ARM 404 response.") from exception
            detail = error.get("error", {}) if isinstance(error, dict) else {}
            code = detail.get("code", "") if isinstance(detail, dict) else ""
            accepted = {"resourcenotfound", "parentresourcenotfound", "resourcegroupnotfound"}
            kind = resource_type(resource) if "/providers/" in resource.lower() else ""
            if kind == ROLE_TYPE:
                accepted.add("roleassignmentnotfound")
            elif kind == DEPLOYMENT_TYPE:
                accepted.add("deploymentnotfound")
            if not isinstance(code, str) or code.lower() not in accepted:
                raise RuntimeError("ARM 404 did not prove that the target resource is absent.")
        value = response.json() if response.content and response.status_code != 404 else None
        return response.status_code, value, response.headers

    def pages(self, resource, api):
        status, page, _ = self.request("GET", resource, api)
        if status != 200:
            raise RuntimeError("Ownership inventory did not return HTTP 200.")
        result = []
        while True:
            result.extend(page["value"])
            link = page.get("nextLink")
            if not link:
                return result
            parsed = urlsplit(link)
            if (parsed.scheme != "https" or parsed.netloc != urlsplit(self.endpoint).netloc
                    or parsed.path.lower() != resource.lower() or parsed.fragment):
                raise ValueError("Ownership inventory returned an unexpected continuation.")
            response = self.send("GET", link)
            if response.status_code != 200:
                raise RuntimeError(f"Ownership inventory failed with HTTP {response.status_code}.")
            page = response.json()

    def api_for(self, resource):
        record = self.journal.records().get(resource.lower())
        if record:
            return record["api"]
        kind = resource_type(resource)
        if kind == ROLE_TYPE:
            return "2022-04-01"
        if kind == DEPLOYMENT_TYPE:
            return "2022-09-01"
        namespace, name = kind.split("/", 1)
        path = f"/subscriptions/{self.journal.context['subscription']}/providers/{namespace}"
        status, provider, _ = self.request("GET", path, "2021-04-01")
        if status != 200:
            raise RuntimeError("Cannot discover the owned resource's cleanup API.")
        matches = [item for item in provider["resourceTypes"] if item["resourceType"].lower() == name]
        if len(matches) != 1:
            raise ValueError("Resource provider did not return an unambiguous resource type.")
        versions = [version for version in matches[0]["apiVersions"] if API.fullmatch(version)]
        if not versions:
            raise ValueError("Resource provider did not advertise a usable cleanup API.")
        return sorted(versions, key=lambda version: ("preview" not in version, version), reverse=True)[0]

    def verify(self, resource, api):
        status, value, _ = self.request("GET", resource, api)
        if status == 404:
            return None
        if (status != 200 or not isinstance(value, dict)
                or value.get("id", "").lower() != resource.lower() or not self.journal.owns(value)):
            raise ValueError("Refusing to mutate a resource without matching attempt ownership.")
        self.journal.record(
            resource, api, confirmed=True, **({"settled": True} if creation_settled(value) else {}),
        )
        return value


class Observer:
    def __init__(self, journal, arm):
        self.journal, self.arm = journal, arm
        self.original_send = None

    def prepare_root(self, resource, api, body, method, creation_id=None):
        previous = self.arm.verify(resource, api)
        record = self.journal.records().get(resource, {})
        if previous is None and method == "DELETE" and record.get("confirmed"):
            return {"If-Match": record["etag"]} if record.get("etag") else {}
        if previous is None and method != "PUT":
            raise ValueError("A mutation requires an existing owned resource or an initial PUT.")
        if method == "DELETE":
            self.journal.record(resource, api, confirmed=True, etag=previous.get("etag"))
            return {"If-Match": previous["etag"]} if previous.get("etag") else {}
        headers = {"If-None-Match": "*"} if previous is None else {}
        creation = {"creates": {creation_id or uuid4().hex: None}} if previous is None else {}
        kind = resource_type(resource)
        if kind == ROLE_TYPE:
            properties = body.setdefault("properties", {})
            description = properties.get("description") or ""
            if description.startswith(f"{TAG}=") and not description.startswith(self.journal.role_prefix):
                raise ValueError("A role assignment requested another attempt's ownership.")
            if not description.startswith(self.journal.role_prefix):
                properties["description"] = self.journal.role_prefix + description
            self.journal.record(resource, api, kind="role", confirmed=previous is not None, **creation)
            return headers
        if previous is None and "location" not in body:
            raise ValueError("Unrecognized top-level resource; ownership tagging cannot be assumed.")
        shape = record.get("tagShape", "null")
        if "tags" in body:
            shape = "null" if body["tags"] is None else "object"
        tags = body.get("tags") if "tags" in body else (previous or {}).get("tags")
        tags = dict(tags or {})
        if tags.get(TAG, self.journal.owner) != self.journal.owner:
            raise ValueError("A resource requested another attempt's ownership tag.")
        tags[TAG] = self.journal.owner
        body["tags"] = tags
        self.journal.record(resource, api, kind="root", tagShape=shape, confirmed=previous is not None, **creation)
        return headers

    def prepare_deployment(self, resource, api, body, creation_id=None):
        properties = body.get("properties", {})
        template = properties.get("template")
        if (properties.get("mode") != "Incremental" or not isinstance(template, dict)
                or properties.get("templateLink")):
            raise ValueError("Live tests require an inline incremental ARM deployment.")
        status, previous, _ = self.arm.request("GET", resource, api)
        if status != 404 and (status != 200 or not self.journal.owns(previous)):
            raise ValueError("Refusing to reuse another attempt's ARM deployment.")
        parameters = properties.setdefault("parameters", {})
        declared = template.setdefault("parameters", {})
        if PARAMETER in parameters or PARAMETER in declared:
            if parameters.get(PARAMETER, {}).get("value") != self.journal.owner:
                raise ValueError("ARM deployment has a conflicting ownership parameter.")
        declared[PARAMETER] = {"type": "string"}
        parameters[PARAMETER] = {"value": self.journal.owner}
        resources = template.get("resources", {})
        resources = list(resources.values()) if isinstance(resources, dict) else resources
        apis = {}
        for item in resources:
            kind = item.get("type", "").lower()
            if (not kind.startswith("microsoft.") or kind == DEPLOYMENT_TYPE
                    or item.get("resources") or item.get("subscriptionId") or item.get("resourceGroup")):
                raise ValueError("Nested or cross-scope deployments require an explicit ownership adapter.")
            apis[kind] = item.get("apiVersion")
            if item.get("existing") or item.get("scope") or kind.count("/") != 1:
                continue
            if "location" not in item:
                raise ValueError("ARM deployment contains an untaggable top-level resource.")
            tags = item.get("tags") or {}
            if not isinstance(tags, dict) or tags.get(TAG, self.journal.owner) != self.journal.owner:
                raise ValueError("ARM deployment ownership requires literal, nonconflicting tags.")
            item["tags"] = {**tags, TAG: self.journal.owner}
        status, prediction, headers = self.arm.request("POST", resource + "/whatIf", api, body)
        deadline = time.monotonic() + 180
        location = headers.get("Location") or headers.get("location")
        while status == 202 or (
                status == 200 and prediction.get("status", "").lower() in {"running", "accepted", "inprogress"}):
            parsed = urlsplit(location or "")
            if (parsed.scheme != "https" or parsed.netloc != urlsplit(self.arm.endpoint).netloc
                    or not parsed.path.lower().startswith(
                        f"/subscriptions/{self.journal.context['subscription'].lower()}/")
                    or parsed.fragment or time.monotonic() >= deadline):
                raise ValueError("ARM ownership prediction has an invalid or expired polling location.")
            time.sleep(2)
            status, prediction, headers = self.arm.request("GET", parsed.path, api, query=parsed.query)
            location = headers.get("Location") or headers.get("location") or location
        if status != 200 or prediction.get("status", "").lower() != "succeeded":
            raise ValueError("ARM ownership prediction did not complete successfully.")
        targets = self.deployment_targets(prediction)
        roots = {"/".join(target.split("/")[:9]) for target in targets}
        created = []
        creation_id = creation_id or uuid4().hex
        for root in sorted(roots):
            root_api = apis.get(resource_type(root)) or self.arm.api_for(root)
            existing = self.arm.verify(root, root_api)
            if existing is None:
                if root not in targets or resource_type(root) not in apis:
                    raise ValueError("ARM deployment references an unowned parent resource.")
                self.journal.record(
                    root, root_api, kind="root", tagShape="null", creates={creation_id: None},
                    deployments={creation_id: {"id": resource, "api": api}},
                )
                created.append(root)
        self.journal.record(resource, api, kind="deployment")
        return created

    def deployment_targets(self, prediction):
        changes = prediction.get("properties", {}).get("changes")
        if not isinstance(changes, list):
            raise ValueError("ARM ownership prediction omitted its resource changes.")
        targets = set()
        for change in changes:
            if not isinstance(change, dict) or not change.get("resourceId"):
                raise ValueError("ARM ownership prediction omitted a resource ID.")
            if change.get("changeType") == "Ignore":
                continue
            if change.get("changeType") not in {"Create", "Modify", "NoChange", "Deploy"}:
                raise ValueError("ARM ownership prediction contains an unsupported change.")
            targets.add(self.journal.resource_id(change["resourceId"]))
        return targets

    def prepare_tags(self, resource, body, method):
        root = resource.removesuffix("/providers/microsoft.resources/tags/default")
        root_api = self.arm.api_for(root)
        if self.arm.verify(root, root_api) is None or method == "DELETE":
            raise ValueError("Tag operations must retain an existing resource's ownership marker.")
        operation = body.get("operation", "Replace")
        tags = body.get("properties", {}).get("tags")
        if not isinstance(tags, dict) or tags.get(TAG, self.journal.owner) != self.journal.owner:
            raise ValueError("Tag operation has an invalid or conflicting ownership payload.")
        if operation == "Delete":
            if TAG in tags:
                raise ValueError("Deleting the attempt ownership tag is not permitted.")
        elif operation in {"Merge", "Replace"}:
            tags[TAG] = self.journal.owner
        else:
            raise ValueError("Unsupported ownership tag operation.")
        self.journal.record(root, root_api, tagShape="object")

    def visible(self, value, resource="", records=None):
        if records is None:
            records = self.journal.records()
        if isinstance(value, list):
            return [self.visible(item, resource, records) for item in value]
        if not isinstance(value, dict):
            return value
        resource = value.get("id", resource)
        resource = resource.lower() if isinstance(resource, str) else ""
        resource = resource.removesuffix("/providers/microsoft.resources/tags/default")
        value = {key: self.visible(item, resource, records) for key, item in value.items()}
        tags = value.get("tags")
        if isinstance(tags, dict) and tags.get(TAG) == self.journal.owner:
            tags.pop(TAG)
            record = records.get(resource, {})
            if not tags and record.get("tagShape", "null") == "null":
                value["tags"] = None
        description = value.get("description")
        if isinstance(description, str) and description.startswith(self.journal.role_prefix):
            value["description"] = description.removeprefix(self.journal.role_prefix) or None
        return value

    def observe_response(self, resource, api, response, created, creation_id):
        for created_resource in created:
            record = self.journal.records()[created_resource]
            self.journal.record(created_resource, record["api"], creates={creation_id: response.status_code})
        if response.content:
            try:
                value = response.json()
            except ValueError:
                return response
            if (200 <= response.status_code < 300 and isinstance(value, dict)
                    and value.get("id", "").lower() == resource
                    and resource.startswith(self.journal.group + "/providers/")
                    and self.journal.owns(value)):
                self.journal.record(
                    resource, api, confirmed=True, etag=value.get("etag") or response.headers.get("ETag"),
                    **({"settled": True} if creation_settled(value, response.status_code) else {}),
                )
            response._content = json.dumps(self.visible(value)).encode("utf-8")
            response.headers["Content-Length"] = str(len(response.content))
        return response

    def install(self):
        import requests
        from knack.util import CLIError

        self.original_send = requests.Session.send

        def send(session, request, **kwargs):
            parsed = urlsplit(request.url)
            known_arm = parsed.hostname in {
                urlsplit(endpoint).hostname for cloud in CLOUDS for endpoint in cloud_endpoints(cloud)
            }
            if not known_arm:
                return self.original_send(session, request, **kwargs)
            method = request.method.upper()
            resource = parsed.path.rstrip("/").lower()
            api = parse_qs(parsed.query).get("api-version", [None])[0]
            creation_id, created = uuid4().hex, []
            if method in {"PUT", "PATCH", "DELETE"}:
                try:
                    if parsed.netloc not in {
                        urlsplit(endpoint).netloc for endpoint in cloud_endpoints(self.journal.context["cloud"])
                    }:
                        raise ValueError("ARM mutation targets another Azure cloud.")
                    resource = self.journal.resource_id(resource)
                    body = request_body(request.body)
                    if resource_type(resource) == DEPLOYMENT_TYPE:
                        if method == "PUT":
                            created = self.prepare_deployment(resource, api, body, creation_id)
                        else:
                            self.arm.verify(resource, api)
                    elif resource.endswith("/providers/microsoft.resources/tags/default"):
                        self.prepare_tags(resource, body, method)
                    elif len(resource.split("/")) == 9 or resource_type(resource) == ROLE_TYPE:
                        headers = self.prepare_root(resource, api, body, method, creation_id)
                        if headers.get("If-None-Match") == "*":
                            created = [resource]
                        for name, value in headers.items():
                            request.headers.setdefault(name, value)
                    else:
                        root = "/".join(resource.split("/")[:9])
                        if self.arm.verify(root, self.arm.api_for(root)) is None:
                            prior = self.journal.records().get(root, {})
                            if method != "DELETE" or not prior.get("confirmed"):
                                raise ValueError("Child resource mutation requires an existing owned parent.")
                    if method in {"PUT", "PATCH"}:
                        request.prepare_body(data=None, files=None, json=body)
                except (CLIError, OSError, RuntimeError, ValueError) as error:
                    self.journal.violation(method, resource, error)
                    raise
            response = self.original_send(session, request, **kwargs)
            return self.observe_response(resource, api, response, created, creation_id)

        requests.Session.send = send

    def uninstall(self):
        if self.original_send is not None:
            import requests
            requests.Session.send = self.original_send


def activate(path):
    """Keep subprocess az commands on the same Python/CLI and ownership context."""
    journal = Journal(path)
    source = str(Path(__file__).resolve())
    interpreter = (sys.executable + "\n" + source).encode()
    directory = journal.path.parent / ("owned-cli-" + hashlib.sha256(interpreter).hexdigest()[:12])
    directory.mkdir(exist_ok=True)
    launcher = directory / "az"
    content = f"#!{sys.executable}\nimport runpy\nrunpy.run_path({source!r})['cli']()\n"
    try:
        publish(launcher, content.encode("utf-8"), mode=0o700)
    except FileExistsError:
        pass
    if launcher.read_text(encoding="utf-8") != content or not os.access(launcher, os.X_OK):
        raise ValueError("Ownership CLI launcher belongs to another source.")
    os.environ[ENV] = str(journal.path)
    os.environ["PATH"] = str(directory) + os.pathsep + os.environ["PATH"]
    return journal


def pending_creates(record):
    return {
        creation for creation, status in record.get("creates", {}).items()
        if record.get("createTimes", {}).get(creation, 0) >= record.get("settledNs", 0)
        and (status is None or not 400 <= status < 500 or status in (408, 429))
    }


def deployment_finished(journal, arm, record, creation):
    deployment = record.get("deployments", {}).get(creation)
    if not deployment:
        return False
    resource = journal.resource_id(deployment["id"])
    if resource_type(resource) != DEPLOYMENT_TYPE:
        raise ValueError("A template creation must reference an owned ARM deployment.")
    current = arm.verify(resource, deployment["api"])
    return current is not None and (
        current.get("properties", {}).get("provisioningState", "").lower() in TERMINAL_STATES
    )


def cleanup_submit(journal, arm, resource, record):
    if time.monotonic() >= arm.deadline:
        raise TimeoutError("Attempt cleanup budget expired.")
    current = arm.verify(resource, record["api"])
    if current is None:
        pending = pending_creates(record)
        if pending:
            if not all(deployment_finished(journal, arm, record, creation) for creation in pending):
                return "creation"
            # The root can appear between its first GET and the deployment's terminal result.
            current = arm.verify(resource, record["api"])
        if current is None:
            journal.record(resource, record["api"], cleanup="absent")
            return None
    state = (current.get("properties", {}).get("provisioningState") or "").lower()
    if state == "deleting":
        return "deletion"
    if not creation_settled(current):
        return "creation"
    headers = {"If-Match": current["etag"]} if current.get("etag") else None
    arm.request("DELETE", resource, record["api"], headers=headers)
    return "deletion"


def cleanup_batch(journal, arm, batch):
    from knack.util import CLIError

    failures = []
    errors = (CLIError, OSError, RuntimeError, ValueError)

    def failed(resource, api, error):
        failures.append(resource)
        journal.record(resource, api, cleanup="failed", errorType=type(error).__name__)
        print(f"Cleanup pending for {resource}: {type(error).__name__}", file=sys.stderr, flush=True)

    pending = {}
    for resource, record in batch:
        try:
            state = cleanup_submit(journal, arm, resource, record)
            if state:
                pending[resource] = (record, state)
        except errors as error:
            failed(resource, record["api"], error)
    while pending and time.monotonic() < arm.deadline:
        for resource, (record, state) in list(pending.items()):
            try:
                if state == "creation":
                    state = cleanup_submit(journal, arm, resource, record)
                    pending[resource] = (record, state)
                else:
                    status, _, _ = arm.request("GET", resource, record["api"])
                    if status == 404:
                        journal.record(resource, record["api"], cleanup="absent")
                        state = None
                if state is None:
                    del pending[resource]
            except errors as error:
                failed(resource, record["api"], error)
                del pending[resource]
        if pending:
            time.sleep(min(5, max(0, arm.deadline - time.monotonic())))
    for resource, (record, _) in pending.items():
        failed(resource, record["api"], TimeoutError("Attempt cleanup budget expired."))
    return failures


def cleanup(path, timeout=600):
    from knack.util import CLIError

    journal = Journal(path)
    arm = Arm(journal)
    arm.deadline = time.monotonic() + timeout
    records = journal.records()
    inventories = (
        (journal.group + "/resources", "2021-04-01"),
        (journal.group + "/providers/Microsoft.Authorization/roleAssignments", "2022-04-01"),
        (journal.group + "/providers/Microsoft.Resources/deployments", "2022-09-01"),
    )
    failures = []
    errors = (CLIError, OSError, RuntimeError, ValueError)
    for collection, api in inventories:
        try:
            for resource in arm.pages(collection, api):
                if journal.owns(resource):
                    resource_id = journal.resource_id(resource["id"])
                    if resource_id not in records:
                        records[resource_id] = journal.record(resource_id, arm.api_for(resource_id), recovered=True)
        except errors as error:
            failures.append(collection)
            print(f"Cleanup inventory failed for {collection}: {type(error).__name__}", file=sys.stderr, flush=True)
    priority = {
        ROLE_TYPE: 0, "microsoft.deviceregistry/assets": 1,
        "microsoft.iotoperations/instances": 2, "microsoft.deviceregistry/assetendpointprofiles": 3,
        "microsoft.secretsync/secretsyncs": 4,
        "microsoft.secretsync/azurekeyvaultsecretproviderclasses": 5,
        "microsoft.extendedlocation/customlocations": 6,
        "microsoft.kubernetes/connectedclusters": 7,
        "microsoft.deviceregistry/namespaces": 8, "microsoft.deviceregistry/schemaregistries": 8,
        "microsoft.storage/storageaccounts": 10, DEPLOYMENT_TYPE: 11,
    }

    def order(item):
        return priority.get(resource_type(item[0]), 9)

    for _, batch in groupby(sorted(records.items(), key=order), key=order):
        failures.extend(cleanup_batch(journal, arm, batch))
    if failures:
        raise RuntimeError("Owned-resource cleanup is incomplete; retain the ownership context and retry.")
    if journal.has_violations():
        raise RuntimeError("Ownership guard rejected mutations; this attempt cannot qualify even after cleanup.")


def cli():
    observer = Observer(Journal(os.environ[ENV]), None)
    observer.arm = Arm(observer.journal)
    observer.install()
    runpy.run_module("azure.cli", run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["cleanup"])
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--cloud", choices=list(CLOUDS), required=True)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--resource-group", required=True)
    args = parser.parse_args()
    context = Journal(args.manifest).context
    if (context["cloud"] != args.cloud or context["subscription"].lower() != args.subscription.lower()
            or context["resourceGroup"].lower() != args.resource_group.lower()):
        raise ValueError("Recovery scope differs from the original ownership manifest.")
    cleanup(args.manifest)
