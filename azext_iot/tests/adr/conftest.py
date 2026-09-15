# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
from unittest.mock import Mock, patch

import pytest

from azext_iot.adr.providers.base import ADRProvider
from azext_iot.adr.providers.namespace import NamespaceProvider
from azext_iot.tests.adr._log import _log, _pretty_log_enabled
from azext_iot.tests.generators import generate_generic_id

TEST_RG = os.getenv("azext_iot_adr_resource_group") or os.getenv("azext_iot_testrg")
TEST_SUBSCRIPTION = os.getenv("azext_iot_testsubscription")
TEST_LOCATION = os.getenv("azext_iot_adr_location", "centraluseuap")
TEST_API_VERSION = os.getenv("azext_iot_adr_api_version", "2026-04-01")


def pytest_runtest_logreport(report):
    if not _pretty_log_enabled() or report.when != "call":
        return
    test_name = report.nodeid.split("::")[-1]
    if report.passed:
        _log("_pass", "%s", test_name)
    elif report.failed:
        short_reason = ""
        if report.longreprtext:
            for line in report.longreprtext.splitlines():
                line = line.strip()
                if line and not line.startswith("_"):
                    short_reason = f" -- {line[:200]}"
                    break
        _log("_fail", "%s%s", test_name, short_reason)


@pytest.fixture()
def fixture_adr_provider(fixture_cmd):
    with patch("azext_iot.adr.providers.base.adr_service_factory", return_value=Mock()):
        return ADRProvider(fixture_cmd)


@pytest.fixture()
def fixture_namespace_provider(fixture_cmd):
    with patch("azext_iot.adr.providers.base.adr_service_factory", return_value=Mock()):
        return NamespaceProvider(fixture_cmd)


def generate_adr_namespace_name() -> str:
    return f"testadr{generate_generic_id()[:8]}"
