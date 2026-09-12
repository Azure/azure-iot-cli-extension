# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Private, JSON-only CSR registration process; not an Azure CLI command."""

import json
import re
import ssl
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

# -I excludes the current directory/PYTHONPATH; anchor imports to the caller's extension.
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from azure.cli.core.extension import get_extension_path
    from azext_iot.constants import EXTENSION_NAME

    # Checkout-backed commands still need dependencies from the CLI's extension installation.
    extension_path = get_extension_path(EXTENSION_NAME)
    if extension_path and Path(extension_path).is_dir() and extension_path not in sys.path:
        sys.path.insert(1, extension_path)

from azure.cli.core.azclierror import (
    AzureConnectionError, AzureInternalError, AzureResponseError, BadRequestError, CLIInternalError, ForbiddenError,
    InvalidArgumentValueError, ResourceNotFoundError, UnauthorizedError,
)
from azure.core.exceptions import (
    ClientAuthenticationError, HttpResponseError, ResourceExistsError, ResourceNotFoundError as HttpResourceNotFoundError,
    ServiceRequestError, ServiceResponseError,
)
from knack.log import get_logger


logger = get_logger(__name__)
_STAGES = frozenset(("load-extension", "read-request", "register"))
_FRAME_FILES = {
    str(Path(__file__).resolve().parents[2] / relative): relative
    for relative in (
        "_factory.py", "dps/providers/device_registration.py",
        "dps/services/_registration.py", "dps/services/_registration_worker.py",
        "dps/services/_csr.py", "dps/services/_authentication.py",
        "sdk/dps/device/_client.py", "sdk/dps/device/operations/_operations.py",
    )
}


_ERROR_TYPES = {kind.__name__: kind for kind in (
    AzureConnectionError, AzureInternalError, AzureResponseError, BadRequestError, CLIInternalError, ForbiddenError,
    InvalidArgumentValueError, ResourceNotFoundError, UnauthorizedError,
    ClientAuthenticationError, HttpResponseError, ResourceExistsError, ServiceRequestError, ServiceResponseError,
    ValueError, OSError, FileNotFoundError, PermissionError, ssl.SSLError,
)}
_ERROR_TYPES["HttpResourceNotFoundError"] = HttpResourceNotFoundError
_ERROR_NAMES = {kind: name for name, kind in _ERROR_TYPES.items()}
_TRANSPORT_OPTION_ERRORS = {
    f"Session.request() got an unexpected keyword argument '{option}'":
        f"DPS registration transport rejected request option '{option}'. "
        "This is a client pipeline configuration error."
    for option in ("logging_enable", "connection_timeout", "read_timeout", "retry_total", "raw_response_hook")
}


def _error_to_json(error, secrets, depth=0):
    kind = _ERROR_NAMES.get(type(error))
    message = str(error) if kind else "Unexpected DPS registration worker error ({}).".format(type(error).__name__)
    if type(error) is TypeError:
        message = _TRANSPORT_OPTION_ERRORS.get(str(error), message)
    if type(error) is ModuleNotFoundError and error.name == "msrestazure":
        message = ("DPS registration worker could not load required dependency 'msrestazure'. "
                   "Reinstall the azure-iot extension in the active Azure CLI environment.")
    result = {"type": kind or "CLIInternalError", "message": _redact(message, secrets)}
    if isinstance(error, HttpResponseError):
        result["status_code"] = error.status_code
        details = error.error
        result["code"] = _redact(str(getattr(details, "code", "") or ""), secrets)
        result["service_message"] = _redact(str(getattr(details, "message", "") or ""), secrets)
    if error.__cause__ is not None and depth < 4:
        result["cause"] = _error_to_json(error.__cause__, secrets, depth + 1)
    return result


def _redact(message, secrets):
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[REDACTED]")
    return re.sub(r"SharedAccessSignature [^\r\n]*", "[REDACTED]", message)


def _error_from_json(value):
    kind = _ERROR_TYPES[value["type"]]
    message = value["message"]
    if not isinstance(message, str):
        raise ValueError("Invalid error message.")
    error = kind(message)
    if isinstance(error, HttpResponseError):
        error.status_code = value.get("status_code")
        error.error = SimpleNamespace(code=value.get("code"), message=value.get("service_message"))
    if "cause" in value:
        error.__cause__ = _error_from_json(value["cause"])
    if "diagnostics" in value:
        diagnostics = value["diagnostics"]
        stage, frames = diagnostics["stage"], diagnostics["frames"]
        if stage not in _STAGES or not isinstance(frames, list) or len(frames) > 8:
            raise ValueError("Invalid worker diagnostics.")
        for frame in frames:
            if (
                not isinstance(frame, dict) or set(frame) != {"file", "line"}
                or frame["file"] not in _FRAME_FILES.values()
                or type(frame["line"]) is not int or not 1 <= frame["line"] <= 20000
            ):
                raise ValueError("Invalid worker diagnostic frame.")
        logger.debug("DPS registration worker stage: %s; extension frames: %s", stage, frames)
    return error


def _diagnostics(error, stage):
    frames = []
    trace = error.__traceback__
    examined = 0
    while trace is not None and examined < 32:
        relative = _FRAME_FILES.get(trace.tb_frame.f_code.co_filename)
        if relative is not None and 1 <= trace.tb_lineno <= 20000:
            frames.append({"file": relative, "line": trace.tb_lineno})
        trace = trace.tb_next
        examined += 1
    return {"stage": stage, "frames": frames[-8:]}


def decode_response(output):
    try:
        response = json.loads(output)
        if response["version"] != 1:
            raise ValueError("Unsupported protocol version.")
        if response["ok"] is True and isinstance(response["result"], dict):
            return response["result"]
        if response["ok"] is not False:
            raise ValueError("Invalid result.")
        error = _error_from_json(response["error"])
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        raise CLIInternalError("DPS registration worker returned an invalid response.") from error
    raise error


def main():
    output = sys.stdout
    secrets = []
    stage = "load-extension"
    try:
        # Never mix library output with the protocol, or forward a worker traceback.
        with redirect_stdout(sys.stderr):
            from azext_iot.dps.services import _registration

            if Path(_registration.__file__).resolve() != Path(__file__).with_name("_registration.py").resolve():
                raise CLIInternalError("DPS registration worker loaded an unexpected extension location.")

            stage = "read-request"
            request = json.load(sys.stdin)
            values = request.pop("provider")
            secrets = [values["device_symmetric_key"], values["passphrase"], request["body"].get("csr")]
            stage = "register"
            result = _registration.register_in_worker(values, **request)
        response = {"version": 1, "ok": True, "result": result}
    except Exception as error:  # Exceptions must cross the process boundary, never become a successful empty result.
        response = {"version": 1, "ok": False, "error": _error_to_json(error, secrets)}
        response["error"]["diagnostics"] = _diagnostics(error, stage)
    json.dump(response, output)
    output.flush()


if __name__ == "__main__":
    main()
