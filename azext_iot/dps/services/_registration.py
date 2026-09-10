# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Hard deadline isolation around the single REST registration implementation."""

from contextlib import suppress
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
from pathlib import Path
import subprocess
import sys
from threading import Event, Thread
from time import monotonic, sleep
from types import SimpleNamespace

from azure.cli.core.azclierror import AzureConnectionError, CLIInternalError, InvalidArgumentValueError
from azure.core.exceptions import HttpResponseError, ServiceRequestError, ServiceResponseError

from azext_iot.dps.services._enrollment import handle_service_error


def registration_deadline(timeout):
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise InvalidArgumentValueError("--timeout must be a positive, finite number of seconds.")
    return monotonic() + timeout


def _remaining(deadline):
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise AzureConnectionError(
            "DPS registration timed out. It may still complete; use 'az iot device registration operation-status' to check."
        )
    return remaining


def _wait(headers, deadline):
    value = next((v for k, v in headers.items() if k.casefold() == "retry-after"), None)
    delay = 1.0
    if value is not None:
        try:
            delay = float(value)
        except ValueError:
            try:
                delay = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                delay = 1.0
    if not math.isfinite(delay) or delay < 0:
        delay = 1.0
    if delay >= _remaining(deadline):
        raise AzureConnectionError("DPS registration timed out before the next permitted retry.")
    sleep(delay)


def call_with_deadline(operation, deadline, **kwargs):
    """Retry transient REST errors inside the same deadline, with no redirects."""
    callback = kwargs.pop("cls")
    while True:
        remaining = _remaining(deadline)
        headers = {}

        def capture_headers(response):
            headers.update(response.http_response.headers)
            # Generated response handling types Retry-After as int. Keep the
            # raw HTTP-date in our callback rather than let deserialization fail.
            for key in list(response.http_response.headers):
                if key.casefold() == "retry-after":
                    try:
                        int(response.http_response.headers[key])
                    except ValueError:
                        response.http_response.headers.pop(key)

        try:
            result = operation(
                connection_timeout=remaining / 2, read_timeout=remaining / 2,
                retry_total=0, logging_enable=False, raw_response_hook=capture_headers,
                cls=lambda response, body, _: callback(response, body, headers),
                **kwargs,
            )
            _remaining(deadline)
            return result
        except HttpResponseError as error:
            if error.status_code not in (408, 429, 500, 502, 503, 504):
                handle_service_error(error)
            try:
                _wait(headers or getattr(error.response, "headers", {}) or {}, deadline)
            except AzureConnectionError as timeout_error:
                raise timeout_error from error
        except (ServiceRequestError, ServiceResponseError) as error:
            raise AzureConnectionError("DPS registration connection failed.") from error


def register_with_deadline(provider, body, timeout):
    from azext_iot.dps.services._registration_worker import decode_response

    # Discovery and in-process CLI/bootstrap authentication happen in the caller,
    # not in an isolated CLI process. No secrets are passed as process arguments.
    provider._validate_attestation_params(  # pylint: disable=protected-access
        enrollment_group_id=provider.enrollment_group_id,
        device_symmetric_key=provider._device_symmetric_key_input,  # pylint: disable=protected-access
        compute_key=provider.compute_key,
        certificate_file=provider.certificate_file,
        key_file=provider.key_file,
        passphrase=provider.passphrase,
    )
    deadline = registration_deadline(timeout)
    symmetric_key = provider.device_symmetric_key
    if isinstance(symmetric_key, bytes):
        symmetric_key = symmetric_key.decode("ascii")
    request = {
        "provider": {
            "registration_id": provider.registration_id,
            "id_scope": provider.id_scope,
            "provisioning_host": provider.device_endpoint,
            "device_symmetric_key": symmetric_key,
            "certificate_file": str(Path(provider.certificate_file).resolve()) if provider.certificate_file else None,
            "key_file": str(Path(provider.key_file).resolve()) if provider.key_file else None,
            "passphrase": provider.passphrase,
        },
        "body": body,
        "deadline": deadline,
    }
    _remaining(deadline)
    try:
        worker = subprocess.Popen(  # pylint: disable=consider-using-with
            [sys.executable, "-I", str(Path(__file__).with_name("_registration_worker.py").resolve())],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except OSError as error:
        raise CLIInternalError("Unable to start the DPS registration worker.") from error
    communicator = None
    try:
        communication = {}
        finished = Event()
        communicator = Thread(
            target=_communicate_worker, args=(worker, request, communication, finished),
            name="iot-dps-registration-communicator", daemon=False,
        )
        communicator.start()
        # Windows communicate() writes stdin synchronously; bound that too.
        if not finished.wait(_remaining(deadline)):
            raise AzureConnectionError("DPS registration timed out.")
        if "error" in communication:
            raise communication["error"]
        _remaining(deadline)
        if worker.returncode:
            raise CLIInternalError(f"DPS registration worker exited unexpectedly ({worker.returncode}).")
        return decode_response(communication["output"])
    finally:
        _stop_worker(worker, communicator)


def _communicate_worker(worker, request, communication, finished):
    try:
        communication["output"], _ = worker.communicate(json.dumps(request).encode("utf-8"))
    except BaseException as error:
        communication["error"] = error
    finally:
        finished.set()


def _stop_worker(worker, communicator=None):
    try:
        if worker.poll() is None:
            try:
                with suppress(ProcessLookupError):
                    worker.terminate()
                worker.wait(timeout=0.2)
            except BaseException as error:
                with suppress(ProcessLookupError):
                    worker.kill()
                worker.wait()
                if not isinstance(error, subprocess.TimeoutExpired):
                    raise
    finally:
        try:
            for thread in (communicator, getattr(worker, "stdout_thread", None), getattr(worker, "stderr_thread", None)):
                if thread is not None and thread.ident is not None:
                    thread.join()
        finally:
            for stream in (worker.stdin, worker.stdout, worker.stderr):
                stream.close()


def register_in_worker(values, body, deadline):
    from azext_iot.dps.providers.device_registration import DeviceRegistrationProvider

    provider = DeviceRegistrationProvider(SimpleNamespace(cli_ctx=None), **values)
    try:
        return provider._perform_registration(body, deadline=deadline)  # pylint: disable=protected-access
    finally:
        if provider.client is not None:
            provider.client.close()
