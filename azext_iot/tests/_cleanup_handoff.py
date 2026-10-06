# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Attempt-local records of cleanup submissions, never assertions of resource absence."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
from time import time_ns
from uuid import uuid4

ENV = "azext_iot_cleanup_handoff"


def enabled():
    return bool(os.environ.get(ENV))


def record(resource, status, error_type=None):
    if not enabled():
        return
    directory = Path(os.environ[ENV])
    directory.mkdir(parents=True, exist_ok=True)
    value = {"resource": resource, "status": status, "timeNs": time_ns()}
    if error_type:
        value["errorType"] = error_type
    with (directory / (uuid4().hex + ".json")).open("x", encoding="utf-8") as stream:
        json.dump(value, stream)
    print(f"Cleanup {status}: {resource}", flush=True)
    if status in ("failed", "pending"):
        print(f"##vso[task.logissue type=warning]Cleanup {status}: {resource}", flush=True)


def cleanup(resource, operation, *, accepted=True):
    """Known cleanup failures remain visible without replacing functional test results."""
    from azure.core.exceptions import AzureError
    from knack.util import CLIError
    from msrestazure.azure_exceptions import CloudError

    try:
        result = operation()
    except (AzureError, CLIError, CloudError, RuntimeError, AssertionError, OSError):
        record(resource, "failed", type(sys.exc_info()[1]).__name__)
        return None
    if accepted:
        record(resource, "accepted")
    return result


def summary(directory):
    values = [json.loads(path.read_text(encoding="utf-8")) for path in Path(directory).rglob("cleanup-receipts/*.json")]
    latest = {value["resource"].casefold(): value for value in sorted(values, key=lambda item: item["timeNs"])}
    return [latest[key] for key in sorted(latest)]


@contextmanager
def submission(resource):
    completed = False
    try:
        yield
        completed = True
    finally:
        error = None if completed else sys.exc_info()[1]
        record(resource, "failed" if error else "accepted", type(error).__name__ if error else None)
