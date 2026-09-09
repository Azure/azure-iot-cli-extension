# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""DPS 2026-11-02 device registration and Software Updates actions."""

from dataclasses import dataclass
import re
from time import monotonic, sleep

from azure.cli.core.azclierror import (
    AzureResponseError,
    FileOperationError,
    InvalidArgumentValueError,
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError,
)
from azure.core.exceptions import HttpResponseError

from azext_iot._factory import dps_device_service_factory
from azext_iot.common.shared import AttestationType
from azext_iot.common.utility import (
    handle_service_exception,
    process_json_arg,
    read_file_content,
)
from azext_iot.constants import IOTDPS_PROVISIONING_HOST
from azext_iot.dps.common import (
    CERTIFICATE_FILE_ERROR,
    CERTIFICATE_RETRIEVAL_ERROR,
    COMPUTE_KEY_ERROR,
    DISABLED_REGISTRATION_ERROR,
    FAILED_REGISTRATION_ERROR,
    MISSING_DPS_CREDENTIALS_ERROR,
    TPM_SUPPORT_ERROR,
)
from azext_iot.dps.providers.discovery import DPSDiscovery
from azext_iot.operations.dps import (
    iot_dps_compute_device_key,
    iot_dps_device_enrollment_get,
    iot_dps_device_enrollment_group_get,
)

_REGISTRATION_TIMEOUT_SECONDS = 5 * 60
_REGISTRATION_RETRY_SECONDS = 2
_REGISTRATION_MAX_RETRY_SECONDS = 30
_CSR_PEM = re.compile(
    r"\A\s*-----BEGIN (?P<label>(?:NEW )?CERTIFICATE REQUEST)-----"
    r"\s+.+?\s+-----END (?P=label)-----\s*\Z",
    re.DOTALL,
)


@dataclass(frozen=True)
class _DeviceResponse:
    status_code: int
    body: dict
    headers: dict


def _capture_device_response(pipeline_response, body, headers):
    return _DeviceResponse(
        status_code=pipeline_response.http_response.status_code,
        body=body,
        headers=headers or {},
    )


def _as_device_response(value) -> _DeviceResponse:
    if isinstance(value, _DeviceResponse):
        return value
    # Test doubles and older compatible clients may ignore `cls`. Such a
    # direct return has historically represented a completed response.
    return _DeviceResponse(status_code=200, body=value, headers={})


def _retry_after_seconds(headers, fallback=_REGISTRATION_RETRY_SECONDS):
    value = None
    for key, candidate in (headers or {}).items():
        if str(key).casefold() == "retry-after":
            value = candidate
            break
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 0
    if parsed <= 0:
        parsed = fallback
    return min(parsed, _REGISTRATION_MAX_RETRY_SECONDS)


def _read_csr_argument(value: str) -> str:
    """Accept recognizable inline PEM; otherwise read a path safely."""
    if not isinstance(value, str):
        raise InvalidArgumentValueError(
            "--csr must be an inline PEM certificate signing request or a file path."
        )
    if _CSR_PEM.fullmatch(value):
        return value
    try:
        return read_file_content(value)
    except (OSError, FileOperationError):
        raise InvalidArgumentValueError(
            "Unable to read the --csr file. Verify the path and permissions, "
            "or provide a complete PEM certificate signing request inline."
        ) from None


def _parse_body(value, argument_name):
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = process_json_arg(value, argument_name)
    except Exception as error:
        raise InvalidArgumentValueError(
            f"{argument_name} must be a JSON object or a path to a JSON file."
        ) from error
    if not isinstance(parsed, dict):
        raise InvalidArgumentValueError(
            f"{argument_name} must be a JSON object or a path to a JSON file."
        )
    return parsed


def _sanitize_registration_error_detail(value):
    if not isinstance(value, (str, int)):
        return None
    sanitized = "".join(
        character if character.isprintable() else " "
        for character in str(value)
    )
    return " ".join(sanitized.split()) or None


def _raise_for_terminal_registration(result):
    if not isinstance(result, dict):
        return

    registration_state = result.get("registrationState")
    containers = [result]
    if isinstance(registration_state, dict):
        containers.append(registration_state)

    statuses = {
        status.strip().casefold()
        for container in containers
        if isinstance((status := container.get("status")), str)
    }
    if "disabled" in statuses:
        raise AzureResponseError(DISABLED_REGISTRATION_ERROR)
    if "failed" not in statuses:
        return

    details = []
    for field in ("errorCode", "errorMessage"):
        for container in reversed(containers):
            detail = _sanitize_registration_error_detail(container.get(field))
            if detail:
                details.append(f"{field}: {detail}")
                break
    suffix = f". {'; '.join(details)}" if details else ""
    raise AzureResponseError(f"{FAILED_REGISTRATION_ERROR}{suffix}")


class DeviceRegistrationProvider:
    """Call the public registration operations of the modeless DPS device client."""

    def __init__(
        self,
        cmd,
        registration_id: str,
        id_scope: str = None,
        dps_name: str = None,
        resource_group_name: str = None,
        login: str = None,
        auth_type_dataplane: str = None,
        provisioning_host: str = None,
        enrollment_group_id: str = None,
        device_symmetric_key: str = None,
        compute_key: bool = False,
        certificate_file: str = None,
        key_file: str = None,
        passphrase: str = None,
        *,
        clock=None,
        sleeper=None,
        registration_timeout: int = _REGISTRATION_TIMEOUT_SECONDS,
    ):
        self._validate_explicit_auth_inputs(
            enrollment_group_id=enrollment_group_id,
            device_symmetric_key=device_symmetric_key,
            compute_key=compute_key,
            certificate_file=certificate_file,
            key_file=key_file,
            passphrase=passphrase,
        )
        self.cmd = cmd
        self.registration_id = registration_id
        self.dps_name = dps_name
        self.resource_group_name = resource_group_name
        self.login = login
        self.auth_type_dataplane = auth_type_dataplane
        self.provisioning_host = provisioning_host
        self.enrollment_group_id = enrollment_group_id
        self._device_symmetric_key_input = device_symmetric_key
        self.compute_key = compute_key
        self.certificate_file = certificate_file
        self.key_file = key_file
        self.passphrase = passphrase
        self.device_symmetric_key = None
        self._target = None
        self.client = None
        self._clock = clock or monotonic
        self._sleep = sleeper or sleep
        self._registration_timeout = registration_timeout
        self._has_explicit_supported_auth = bool(device_symmetric_key) or bool(
            certificate_file and key_file
        )

        # ID scope identifies a DPS tenant but does not identify its device
        # endpoint. A supplied name/login must still be resolved even when the
        # caller also supplied the ID scope and device credentials.
        self.id_scope = id_scope
        if self.dps_name or self.login:
            self._get_target()
        if not self.id_scope:
            self.id_scope = self._get_idscope()

    @staticmethod
    def _validate_explicit_auth_inputs(
        enrollment_group_id: str = None,
        device_symmetric_key: str = None,
        compute_key: bool = False,
        certificate_file: str = None,
        key_file: str = None,
        passphrase: str = None,
    ):
        symmetric_mode = device_symmetric_key is not None or compute_key
        x509_mode = any(
            value is not None
            for value in (certificate_file, key_file, passphrase)
        )
        if symmetric_mode and x509_mode:
            raise MutuallyExclusiveArgumentError(
                "Symmetric-key and X.509 authentication inputs cannot be "
                "combined. Choose --symmetric-key (optionally --compute-key) "
                "or a certificate/key file pair."
            )
        if device_symmetric_key is not None and not device_symmetric_key:
            raise InvalidArgumentValueError("--symmetric-key cannot be empty.")
        if x509_mode and (not certificate_file or not key_file):
            raise RequiredArgumentMissingError(CERTIFICATE_FILE_ERROR)
        if compute_key and not (device_symmetric_key or enrollment_group_id):
            raise RequiredArgumentMissingError(COMPUTE_KEY_ERROR)

    def _get_target(self):
        if self._target is None:
            self._target = DPSDiscovery(self.cmd).get_target(
                self.dps_name,
                self.resource_group_name,
                login=self.login,
                auth_type=self.auth_type_dataplane,
            )
        return self._target

    def _get_idscope(self) -> str:
        target = self._get_target()
        if target.get("idscope"):
            return target["idscope"]
        if not target.get("entity"):
            raise RequiredArgumentMissingError(
                "Provide --id-scope or a DPS identifier that can be resolved."
            )
        dps_name = target["entity"].split(".", 1)[0]
        return DPSDiscovery(self.cmd).get_id_scope(
            resource_name=dps_name, rg=self.resource_group_name
        )

    def _validate_attestation_params(
        self,
        enrollment_group_id: str = None,
        device_symmetric_key: str = None,
        compute_key: bool = False,
        certificate_file: str = None,
        key_file: str = None,
        passphrase: str = None,
    ):
        self.device_symmetric_key = None
        self.certificate_file = None
        self.key_file = None
        self.passphrase = None
        if device_symmetric_key:
            self.device_symmetric_key = (
                iot_dps_compute_device_key(
                    cmd=self.cmd,
                    registration_id=self.registration_id,
                    enrollment_id=enrollment_group_id,
                    symmetric_key=device_symmetric_key,
                    dps_name=self.dps_name,
                    resource_group_name=self.resource_group_name,
                    login=self.login,
                    auth_type_dataplane=self.auth_type_dataplane,
                )
                if compute_key
                else device_symmetric_key
            )
        elif certificate_file or key_file or passphrase:
            if not certificate_file or not key_file:
                raise RequiredArgumentMissingError(CERTIFICATE_FILE_ERROR)
            self.certificate_file = certificate_file
            self.key_file = key_file
            self.passphrase = passphrase
        elif not (self.dps_name or self.login):
            raise RequiredArgumentMissingError(MISSING_DPS_CREDENTIALS_ERROR)
        else:
            self._get_attestation_params(
                enrollment_group_id=enrollment_group_id
            )

    def _get_attestation_params(self, enrollment_group_id: str = None):
        if enrollment_group_id:
            attestation = iot_dps_device_enrollment_group_get(
                cmd=self.cmd,
                enrollment_id=enrollment_group_id,
                dps_name=self.dps_name,
                resource_group_name=self.resource_group_name,
                login=self.login,
                auth_type_dataplane=self.auth_type_dataplane,
            )["attestation"]
            if attestation["type"] == AttestationType.symmetricKey.value:
                self.device_symmetric_key = iot_dps_compute_device_key(
                    cmd=self.cmd,
                    registration_id=self.registration_id,
                    enrollment_id=enrollment_group_id,
                    dps_name=self.dps_name,
                    resource_group_name=self.resource_group_name,
                    login=self.login,
                    auth_type_dataplane=self.auth_type_dataplane,
                )
            elif attestation["type"] == AttestationType.x509.value:
                raise InvalidArgumentValueError(
                    CERTIFICATE_RETRIEVAL_ERROR
                )
            else:
                raise InvalidArgumentValueError(TPM_SUPPORT_ERROR)
            return

        enrollment = iot_dps_device_enrollment_get(
            cmd=self.cmd,
            enrollment_id=self.registration_id,
            dps_name=self.dps_name,
            resource_group_name=self.resource_group_name,
            login=self.login,
            auth_type_dataplane=self.auth_type_dataplane,
        )
        attestation = enrollment["attestation"]
        if attestation["type"] == AttestationType.symmetricKey.value:
            if "primaryKey" not in (attestation.get("symmetricKey") or {}):
                enrollment = iot_dps_device_enrollment_get(
                    cmd=self.cmd,
                    enrollment_id=self.registration_id,
                    show_keys=True,
                    dps_name=self.dps_name,
                    resource_group_name=self.resource_group_name,
                    login=self.login,
                    auth_type_dataplane=self.auth_type_dataplane,
                )
            self.device_symmetric_key = enrollment["attestation"][
                "symmetricKey"
            ]["primaryKey"]
        elif attestation["type"] == AttestationType.x509.value:
            raise InvalidArgumentValueError(CERTIFICATE_RETRIEVAL_ERROR)
        else:
            raise InvalidArgumentValueError(TPM_SUPPORT_ERROR)

    def _get_dps_device_sdk(self):
        endpoint = (
            self.provisioning_host
            or (self._target or {}).get("deviceHostName")
            or IOTDPS_PROVISIONING_HOST
        )
        if "://" not in endpoint:
            endpoint = f"https://{endpoint}"
        return dps_device_service_factory(
            self.cmd.cli_ctx,
            endpoint=endpoint,
            registration_id=self.registration_id,
            id_scope=self.id_scope,
            device_symmetric_key=self.device_symmetric_key,
            certificate_file=self.certificate_file,
            key_file=self.key_file,
            passphrase=self.passphrase,
        )

    def _get_client(self):
        if self.client is None:
            self._validate_attestation_params(
                enrollment_group_id=self.enrollment_group_id,
                device_symmetric_key=self._device_symmetric_key_input,
                compute_key=self.compute_key,
                certificate_file=self.certificate_file,
                key_file=self.key_file,
                passphrase=self.passphrase,
            )
            self.client = self._get_dps_device_sdk()
        return self.client

    def create(
        self,
        csr: str = None,
        payload=None,
        endorsement_key: str = None,
        storage_root_key: str = None,
    ):
        body = {
            "registrationId": self.registration_id,
        }
        if csr is not None:
            body["csr"] = _read_csr_argument(csr)
        if payload is not None:
            body["payload"] = _parse_body(payload, "--payload")
        if endorsement_key is not None or storage_root_key is not None:
            if not endorsement_key or not storage_root_key:
                raise RequiredArgumentMissingError(
                    "--endorsement-key and --storage-root-key must be provided together."
                )
            if not (
                self._has_explicit_supported_auth
                or self.dps_name
                or self.login
            ):
                raise InvalidArgumentValueError(
                    f"TPM-only client authentication is unsupported. "
                    f"{TPM_SUPPORT_ERROR} The TPM request fields are retained "
                    "for service schema compatibility, but they do not provide "
                    "a client-side TPM challenge flow. Supply a supported "
                    "symmetric-key or X.509 authentication mode."
                )
            body["tpm"] = {
                "endorsementKey": endorsement_key,
                "storageRootKey": storage_root_key,
            }

        try:
            response = _as_device_response(
                self._get_client().runtime_registration.register_device_and_issue_certificate(
                    registration_id=self.registration_id,
                    id_scope=self.id_scope,
                    device_registration=body,
                    cls=_capture_device_response,
                )
            )
            if response.status_code == 202:
                result = self._wait_for_registration(response)
            else:
                result = response.body
        except HttpResponseError as error:
            return handle_service_exception(error)

        _raise_for_terminal_registration(result)
        return self._correlate_registration(result)

    def _wait_for_registration(self, response: _DeviceResponse):
        operation_id = (response.body or {}).get("operationId")
        if not operation_id:
            raise AzureResponseError(
                "DPS accepted the registration but did not return the "
                "operation ID required to poll it."
            )

        deadline = self._clock() + self._registration_timeout
        current = response
        while current.status_code == 202:
            remaining = deadline - self._clock()
            if remaining <= 0:
                break
            self._sleep(
                min(
                    _retry_after_seconds(current.headers),
                    remaining,
                )
            )
            if deadline - self._clock() <= 0:
                break
            try:
                current = _as_device_response(
                    self._get_client().runtime_registration.operation_status_lookup_preview(
                        registration_id=self.registration_id,
                        operation_id=operation_id,
                        id_scope=self.id_scope,
                        cls=_capture_device_response,
                    )
                )
            except HttpResponseError as error:
                status_code = getattr(error, "status_code", None)
                if status_code not in (408, 429) and not (
                    status_code is not None and status_code >= 500
                ):
                    raise
                current = _DeviceResponse(
                    status_code=202,
                    body=response.body,
                    headers=getattr(
                        getattr(error, "response", None), "headers", {}
                    )
                    or {},
                )
        if current.status_code == 200:
            return current.body
        raise AzureResponseError(
            "Timed out waiting for DPS registration operation "
            f"'{operation_id}'. The operation may still complete; check it "
            "with 'az iot device registration operation-status' and retry "
            "that read safely."
        )

    def _correlate_registration(self, result):
        registration_state = (result or {}).get("registrationState")
        if isinstance(registration_state, dict):
            external_id = (
                registration_state.get("registrationId")
                or registration_state.get("deviceId")
                or self.registration_id
            )
            registration_state.setdefault("registryDeviceExternalId", external_id)
        return result

    def operation_status(self, operation_id: str):
        try:
            response = _as_device_response(
                self._get_client().runtime_registration.operation_status_lookup_preview(
                    registration_id=self.registration_id,
                    operation_id=operation_id,
                    id_scope=self.id_scope,
                    cls=_capture_device_response,
                )
            )
            return response.body
        except HttpResponseError as error:
            return handle_service_exception(error)
