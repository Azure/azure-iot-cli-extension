# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Private line-framed worker protocol. Progress contains correlation metadata only."""

import json
import re

from azure.cli.core.azclierror import AzureConnectionError, CLIInternalError


MAX_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_PROGRESS_BYTES = 1024
_CORRELATION_TOKEN = re.compile(r"[a-zA-Z0-9._:/+=-]{1,256}\Z")


class RegistrationTimeoutError(AzureConnectionError):
    """Internal deadline signal, enriched after the worker's pipes have been reaped."""


def is_operation_id(value):
    return isinstance(value, str) and _CORRELATION_TOKEN.fullmatch(value) is not None


def timeout_message(operation_id=None, registration_id=None, id_scope=None, host=None):
    if not is_operation_id(operation_id):
        return (
            "DPS registration timed out. Operation ID is unknown: no usable acceptance metadata was received. "
            "The request may still complete; do not blindly resubmit registration."
        )
    # Never interpolate arbitrary service output or credentials into a suggested command.
    registration_id = registration_id if is_operation_id(registration_id) else "<registration-id>"
    id_scope = id_scope if is_operation_id(id_scope) else "<id-scope>"
    host = host if is_operation_id(host) else "<same-provisioning-host>"
    return (
        f"DPS registration timed out. Accepted operation ID: {operation_id}. The operation may still complete; "
        "check it with "
        f"'az iot device registration operation-status --operation-id={operation_id} "
        f"--registration-id={registration_id} --id-scope={id_scope} --host={host}'. "
        "Supply the same device authentication or --dps-name/--login bootstrap options as create "
        "(including --group-id and --compute-key when used). "
        "Retry this status read safely rather than resubmitting registration."
    )


def write_frame(output, value):
    output.write(json.dumps(value, separators=(",", ":")) + "\n")
    output.flush()


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate protocol field.")
        result[key] = value
    return result


def read_frames(stream, communication):
    """Accept at most one progress frame and one final response, requiring newline + EOF.

    Keep the first validated ID even if a later frame is truncated or invalid. The
    caller consumes it only after pipe-reader threads have joined, including on
    timeout. Neither stderr nor rejected protocol bytes become diagnostics.
    """
    consumed = 0
    while True:
        frame = stream.readline(MAX_OUTPUT_BYTES - consumed + 1)
        if not frame:
            if "output" not in communication:
                raise CLIInternalError("DPS registration worker returned an incomplete response.")
            return
        consumed += len(frame)
        if consumed > MAX_OUTPUT_BYTES or not frame.endswith(b"\n") or "output" in communication:
            raise CLIInternalError("DPS registration worker returned an invalid or oversized response.")
        try:
            value = json.loads(frame, object_pairs_hook=_unique_fields)
            if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
                raise ValueError()
            if "accepted" in value:
                accepted = value["accepted"]
                if (
                    len(frame) > MAX_PROGRESS_BYTES or set(value) != {"version", "accepted"}
                    or not isinstance(accepted, dict) or set(accepted) != {"operationId"}
                    or not is_operation_id(accepted["operationId"]) or "operation_id" in communication
                ):
                    raise ValueError()
                communication["operation_id"] = accepted["operationId"]
            elif "ok" in value:
                communication["output"] = frame
            else:
                raise ValueError()
        except (ValueError, TypeError, RecursionError):
            raise CLIInternalError("DPS registration worker returned an invalid response.") from None
