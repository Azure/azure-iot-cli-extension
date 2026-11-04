# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Receipt-owned issuance descendants; external device IDs are never ARM names."""

from contextlib import contextmanager
from hashlib import sha256
import json
from shlex import quote
from urllib.parse import urlsplit

from azure.core.exceptions import HttpResponseError

from azext_iot._factory import adr_service_factory
from azext_iot.tests.adr._helpers import wait_for_condition
from azext_iot.tests.dps import _csr_issuance as csr, _phase_receipts as receipts

RESOLVE_TIMEOUT = 120
DELETE_TIMEOUT = 600


def _read(name):
    path = receipts.settings()[0] / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _conflicted(key):
    # A damaged or empty conflict receipt must not authorize choosing a survivor.
    return (receipts.settings()[0] / f"csr-registry-conflict-{key}.json").exists()


def _completed(intent):
    completed = _read(f"csr-registry-completed-{intent['key']}.json")
    if not completed:
        return False
    resolved = _read(f"csr-registry-resolved-{intent['key']}.json")
    if (completed.get("namespace_id") != intent["namespace_id"] or completed.get("absent") is not True
            or not resolved or completed.get("device_id") != resolved["device"]["id"]):
        raise AssertionError("Malformed RegistryDevice completion receipt cannot release quarantined resources.")
    return True


def require_registry_cleanup_resolved():
    """Keep dedicated targets available for reconciliation of quarantined issuance."""
    for path in receipts.settings()[0].glob("csr-registry-intent-*.json"):
        intent = json.loads(path.read_text(encoding="utf-8"))
        if _conflicted(intent["key"]) or not _completed(intent):
            raise AssertionError(
                "CSR RegistryDevice cleanup is quarantined; retain the dedicated DPS/Hub and ownership receipts."
            )


def require_namespace_cleanup_resolved():
    """A completed device delete cannot substitute for its namespace's cleanup."""
    if not (receipts.settings()[0] / "owned-csrns.json").exists():
        return
    record = _read("owned-csrns.json")
    if not isinstance(record, dict) or not isinstance(record.get("name"), str) or not record["name"]:
        raise AssertionError("CSR namespace ownership claim is malformed; retain the dedicated targets.")
    _, uid, subscription, group = receipts.settings()
    expected_id = (
        f"/subscriptions/{subscription}/resourceGroups/{group}/providers/Microsoft.DeviceRegistry/"
        f"namespaces/{record['name']}"
    )
    if (record.get("kind") != "csrns" or record.get("run_uid") != uid or record.get("phase") != "regular"
            or record.get("subscription") != subscription or record.get("resource_group") != group
            or record["id"].casefold() != expected_id.casefold()):
        raise AssertionError("CSR namespace ownership receipt is inconsistent; retain the dedicated targets.")
    completed = _read("deleted-csrns.json")
    if (not completed or completed.get("delete_completed") is not True
            or any(completed.get(key) != record[key] for key in ("id", "run_uid", "subscription", "phase"))):
        raise AssertionError("CSR namespace absence is not confirmed; retain the dedicated DPS/Hub references.")
    client = adr_service_factory(csr.fixtures.cli.az_cli, subscription_id=subscription)
    try:
        client.namespaces.get(resource_group_name=group, namespace_name=record["name"])
    except HttpResponseError as error:
        if error.status_code == 404:
            return
        raise
    raise AssertionError("CSR namespace absence is not confirmed by current ARM state; retain the dedicated targets.")


def cleanup_registry_devices(namespace_record):
    for path in sorted(receipts.settings()[0].glob("csr-registry-intent-*.json")):
        intent = json.loads(path.read_text(encoding="utf-8"))
        owner = RegistryDeviceOwnership.from_intent(namespace_record, intent)
        owner.cleanup()


class RegistryDeviceOwnership:
    def __init__(self, resource, registration_id):
        self.namespace = receipts._owned(resource["namespace"])  # pylint: disable=protected-access
        dps, hub = resource["dps"], resource["hub"]
        self.intent = {
            "key": sha256(registration_id.encode("utf-8")).hexdigest(),
            "namespace_id": self.namespace["id"], "namespace_name": resource["namespace"],
            "dps_id": dps["dps"]["id"], "dps_name": dps["name"],
            "id_scope": dps["dps"]["properties"]["idScope"],
            "hub_id": hub["hub"]["id"], "hub_name": hub["name"],
            "assigned_hubs": [hub["hub"]["properties"][key] for key in ("hostName", "deviceHostName")],
            "registration_id": registration_id, "device_id": registration_id,
        }
        self.started = False
        self._client = None

    @classmethod
    def from_intent(cls, namespace_record, intent):
        if (intent["namespace_id"] != namespace_record["id"] or intent["namespace_name"] != namespace_record["name"]
                or any(intent.get(key) != namespace_record[key] for key in ("run_uid", "subscription", "phase"))
                or intent["key"] != sha256(intent["registration_id"].encode("utf-8")).hexdigest()
                or intent["device_id"] != intent["registration_id"]):
            raise AssertionError("CSR RegistryDevice intent does not match its owned namespace/registration.")
        for kind in ("dps", "hub"):
            target = receipts._owned(intent[f"{kind}_name"])  # pylint: disable=protected-access
            if target["id"].casefold() != intent[f"{kind}_id"].casefold() or target["kind"] != f"csr{kind}":
                raise AssertionError("CSR registration target intent is not receipt-owned.")
        owner = cls.__new__(cls)
        owner.namespace, owner.intent, owner.started, owner._client = namespace_record, intent, True, None
        return owner

    @property
    def client(self):
        if self._client is None:
            self._client = adr_service_factory(csr.fixtures.cli.az_cli, subscription_id=self.namespace["subscription"])
        return self._client

    @property
    def scope(self):
        return {"resource_group_name": self.namespace["resource_group"], "namespace_name": self.namespace["name"]}

    def _name(self, kind):
        return f"csr-registry-{kind}-{self.intent['key']}.json"

    def _write(self, kind, value, *, exclusive=False):
        receipts.write(self._name(kind), {"namespace_id": self.namespace["id"], **value}, exclusive=exclusive)

    def _snapshot(self, device):
        name, resource_id = device["name"], device["id"]
        if (not isinstance(name, str) or not name or name in (".", "..")
                or any(character in name for character in "/\\?#%")
                or not isinstance(resource_id, str)
                or resource_id.casefold() != f"{self.namespace['id']}/registryDevices/{name}".casefold()):
            raise AssertionError("RegistryDevice response is not an exact direct child of the owned namespace.")
        external_id = device["properties"]["externalDeviceId"]
        if not isinstance(external_id, str) or not external_id:
            raise AssertionError("RegistryDevice response has no authoritative externalDeviceId.")
        if any(value is not None and not isinstance(value, str) for value in (
            device["properties"].get("uuid"), device.get("etag"),
        )):
            raise AssertionError("RegistryDevice identity/version fields are malformed.")
        return {"id": resource_id, "name": name, "external_id": external_id,
                "uuid": device["properties"].get("uuid"), "etag": device.get("etag")}

    def _list(self):
        collection = self.namespace["id"] + "/registryDevices"
        authority = urlsplit(receipts.target()["endpoint"]).netloc

        def validate_page(response):
            http = response.http_response
            if http.status_code != 200:
                return  # The SDK must raise the original service error.
            body = http.json()
            if not isinstance(body, dict) or not isinstance(body.get("value"), list):
                raise AssertionError("Malformed RegistryDevice list cannot establish an ownership baseline.")
            next_link = body.get("nextLink")
            if next_link:
                url = urlsplit(next_link)
                if (url.scheme != "https" or url.netloc != authority
                        or url.path.casefold() != collection.casefold() or url.fragment):
                    raise AssertionError("RegistryDevice pagination escaped the owned namespace.")

        devices = [
            self._snapshot(device)
            for device in self.client.registry_devices.list_by_namespace(**self.scope, raw_response_hook=validate_page)
        ]
        if len({device["id"].casefold() for device in devices}) != len(devices):
            raise AssertionError("Duplicate RegistryDevice IDs cannot establish unambiguous ownership.")
        return devices

    def before_submit(self):
        namespace = csr.find_namespace(self.namespace["name"])
        csr._require_owned(self.namespace["name"], namespace)  # pylint: disable=protected-access
        targets = {}
        for kind in ("dps", "hub"):
            finder = getattr(csr.fixtures, f"_find_{kind}_by_name")
            current = finder(self.intent[f"{kind}_name"])
            record = csr._require_owned(self.intent[f"{kind}_name"], current)  # pylint: disable=protected-access
            if record["id"].casefold() != self.intent[f"{kind}_id"].casefold():
                raise AssertionError("CSR target changed before registration submission.")
            targets[kind] = {kind: current}
        if (targets["dps"]["dps"]["properties"]["idScope"] != self.intent["id_scope"]
                or [targets["hub"]["hub"]["properties"][key] for key in ("hostName", "deviceHostName")]
                != self.intent["assigned_hubs"]):
            raise AssertionError("CSR target registration endpoints changed before submission.")
        csr._assert_linked(namespace, targets["dps"], targets["hub"])  # pylint: disable=protected-access
        self.intent["baseline"] = self._list()
        self._write("intent", self.intent, exclusive=True)
        self.started = True

    def record_result(self, result):
        if not self.started or not isinstance(result, dict):
            raise AssertionError("Registration correlation requires a pre-submission ownership intent and structured result.")
        observed = _read(self._name("result")) or {}
        operation_id = result.get("operationId")
        if operation_id:
            if not isinstance(operation_id, str) or observed.get("operation_id", operation_id) != operation_id:
                raise AssertionError("Registration operation changed while correlating RegistryDevice ownership.")
            observed["operation_id"] = operation_id
            self._write("result", observed)
        state = result.get("registrationState", {})
        if not isinstance(state, dict):
            raise AssertionError("Malformed registration state cannot prove RegistryDevice ownership.")
        for key, expected in (("registrationId", self.intent["registration_id"]), ("deviceId", self.intent["device_id"])):
            if state.get(key) is not None and state[key] != expected:
                self._write("conflict", {"reason": f"Registration {key} changed"})
                raise AssertionError("Registration identity changed; RegistryDevice cleanup is quarantined.")
        if state.get("assignedHub") is not None and state["assignedHub"] not in self.intent["assigned_hubs"]:
            self._write("conflict", {"reason": "Registration Hub changed"})
            raise AssertionError("Registration target changed; RegistryDevice cleanup is quarantined.")
        external_id = state.get("registryDeviceExternalId")
        if (state.get("registrationId") == self.intent["registration_id"]
                and state.get("deviceId") == self.intent["device_id"]
                and state.get("assignedHub") in self.intent["assigned_hubs"] and isinstance(external_id, str) and external_id):
            if observed.get("external_id", external_id) != external_id:
                self._write("conflict", {"reason": "Registration external ID changed"})
                raise AssertionError("Registration external ID changed; RegistryDevice cleanup is quarantined.")
            observed["external_id"] = external_id
            self._write("result", observed)

    def _external_id(self):
        if _conflicted(self.intent["key"]):
            raise AssertionError("Conflicting registration evidence quarantines RegistryDevice cleanup.")
        observed = _read(self._name("result")) or {}
        if observed.get("external_id"):
            return observed["external_id"]
        if observed.get("operation_id"):
            intent = self.intent
            result = csr.invoke(
                f"iot device registration operation-status --dps-name {quote(intent['dps_name'])} "
                f"-g {quote(self.namespace['resource_group'])} --id-scope {quote(intent['id_scope'])} "
                f"--registration-id {quote(intent['registration_id'])} "
                f"--operation-id {quote(observed['operation_id'])} --auth-type login"
            ).as_json()
            self.record_result(result)
            observed = _read(self._name("result")) or {}
            if observed.get("external_id"):
                return observed["external_id"]
        # The service registration GET declares deviceId/assignedHub, not a mapping
        # from a backend-generated external ID. Preserve that read without inventing one.
        state = csr._optional(  # pylint: disable=protected-access
            f"iot dps enrollment registration show --dps-name {quote(self.intent['dps_name'])} "
            f"-g {quote(self.namespace['resource_group'])} --enrollment-id {quote(self.intent['registration_id'])} "
            "--auth-type login --query '{registrationId:registrationId,deviceId:deviceId,assignedHub:assignedHub,status:status}'",
            dataplane=True,
        )
        self._write("unresolved", {"service_registration": state, "observed_devices": self._list()})
        raise AssertionError(
            "RegistryDevice external ID cannot be proven from registration APIs; cleanup is quarantined. "
            "Retain the unique enrollment, dedicated targets and pre-submission intent for reconciliation."
        )

    def _get(self, device):
        try:
            current = self.client.registry_devices.get(**self.scope, registry_device_name=device["name"])
        except HttpResponseError as error:
            if error.status_code == 404:
                return None
            raise
        snapshot = self._snapshot(current)
        if (any(snapshot[key].casefold() != device[key].casefold() for key in ("id", "name"))
                or any(snapshot[key] != device[key] for key in ("external_id", "uuid"))):
            raise AssertionError("RegistryDevice identity changed after ownership resolution; refusing deletion.")
        return current

    def cleanup(self):
        if not self.started:
            return
        if _conflicted(self.intent["key"]):
            raise AssertionError("Conflicting ownership evidence; RegistryDevice cleanup is quarantined.")
        if _completed(self.intent):
            return
        try:
            self._cleanup()
        finally:
            if not _completed(self.intent):
                self._write("quarantine", {
                    "reason": "RegistryDevice cleanup unresolved; preserve the original error and intent.",
                })

    def read_device(self):
        """Resolve current identity without freezing a cleanup ETag before profile actions."""
        if not self.started:
            raise AssertionError("RegistryDevice reads require a pre-submission ownership intent.")
        csr._require_owned(self.namespace["name"], csr.find_namespace(self.namespace["name"]))  # pylint: disable=protected-access
        device = self._resolve_candidate(self._external_id())
        current = wait_for_condition(
            lambda: self._get(device), lambda value: value is not None, description="owned RegistryDevice GET",
            timeout=RESOLVE_TIMEOUT, interval=5, is_retryable_error=lambda _error: False,
        )
        if _read(self._name("observed")) is None:
            self._write("observed", {
                "device": {key: value for key, value in device.items() if key != "etag"},
            }, exclusive=True)
        return current

    @contextmanager
    def certificate_revocation(self, profile_id):
        if not self.started or _read(self._name("resolved")):
            raise AssertionError("Profile mutation requires active ownership before cleanup resolution.")
        action = {"profile_id": profile_id, "completed": False}
        self._write("profile-action", action, exclusive=True)
        yield
        self._write("profile-action", {**action, "completed": True})

    def _resolve_candidate(self, external_id):
        def match():
            matches = [device for device in self._list() if device["external_id"] == external_id]
            if len(matches) > 1:
                self._write("conflict", {
                    "reason": "Ambiguous RegistryDevice external ID",
                    "external_id": external_id, "devices": matches,
                }, exclusive=True)
                raise AssertionError("Ambiguous RegistryDevice external ID; no device will be deleted.")
            return matches

        device = wait_for_condition(
            match, bool, description="owned RegistryDevice materialization",
            timeout=RESOLVE_TIMEOUT, interval=5, is_retryable_error=lambda _error: False,
        )[0]
        if any(old["id"].casefold() == device["id"].casefold() or old["external_id"] == external_id
               for old in self.intent["baseline"]):
            raise AssertionError("RegistryDevice predates this registration; refusing unowned deletion.")
        observed = _read(self._name("observed"))
        if (receipts.settings()[0] / self._name("observed")).exists():
            assert isinstance(observed, dict) and observed.get("namespace_id") == self.namespace["id"], (
                "Malformed RegistryDevice observation cannot establish ownership."
            )
            identity = observed["device"]
            if (any(identity[key].casefold() != device[key].casefold() for key in ("id", "name"))
                    or any(identity[key] != device[key] for key in ("external_id", "uuid"))):
                self._write("conflict", {"reason": "Previously observed RegistryDevice identity changed"})
                raise AssertionError("RegistryDevice identity changed; cleanup is quarantined.")
        return device

    def _cleanup(self):
        action = _read(self._name("profile-action"))
        if (receipts.settings()[0] / self._name("profile-action")).exists():
            if (not isinstance(action, dict) or action.get("completed") is not True
                    or action.get("namespace_id") != self.namespace["id"]):
                raise AssertionError("Uncertain certificate revocation; RegistryDevice cleanup is quarantined.")
        csr._require_owned(self.namespace["name"], csr.find_namespace(self.namespace["name"]))  # pylint: disable=protected-access
        external_id = self._external_id()
        resolved = _read(self._name("resolved"))
        if not resolved:
            device = self._resolve_candidate(external_id)
            self._write("resolved", {"device": device}, exclusive=True)
        else:
            device = resolved["device"]
            if device["external_id"] != external_id:
                raise AssertionError("RegistryDevice receipt and registration external ID disagree.")
        if not _read(self._name("delete")):
            current = wait_for_condition(
                lambda: self._get(device), lambda value: value is not None, description="owned RegistryDevice GET",
                timeout=RESOLVE_TIMEOUT, interval=5, is_retryable_error=lambda _error: False,
            )
            if current.get("etag") != device["etag"]:
                raise AssertionError("RegistryDevice changed before delete; refusing a concurrent update.")
            self._write("delete", {"device_id": device["id"]}, exclusive=True)
            if current["properties"].get("provisioningState") != "Deleting":
                self.client.registry_devices.begin_delete(**self.scope, registry_device_name=device["name"], polling=False)
        wait_for_condition(
            lambda: self._get(device), lambda value: value is None, description="owned RegistryDevice absence",
            timeout=DELETE_TIMEOUT, interval=10, is_retryable_error=lambda _error: False,
        )
        self._write("completed", {"device_id": device["id"], "absent": True}, exclusive=True)
