# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest

from azext_iot.tests.adr import _helpers as helpers
from azext_iot.tests.adr import _readiness as readiness
from azext_iot.tests.adr import test_adr_certificate_authority_int as ca
from azext_iot.tests.adr import test_adr_link_int as links
from azext_iot.tests.adr import test_adr_update_instance_int as instances


def test_cold_su_instance_includes_existing_readiness_and_cleanup_budgets():
    scenario = instances.TestADRUpdateInstanceLifecycle.test_update_instance_lifecycle
    readiness = helpers.SU_PROVISIONING_MAX_POLLS * helpers.SU_PROVISIONING_POLL_INTERVAL
    assert readiness == 3600
    assert helpers.SU_LIFECYCLE_TIMEOUT == readiness + 900
    markers = [mark for mark in getattr(scenario, "pytestmark", []) if mark.name == "timeout"]
    assert len(markers) == 1
    assert markers[0].args == (4500,)
    assert markers[0].kwargs == {"func_only": False}


@pytest.mark.parametrize("scenario", [
    instances.TestADRUpdateInstanceValidation.test_update_instance_validation_negatives,
    ca.TestADRCertificateAuthorityLifecycle.test_adr_certificate_authority_lifecycle,
])
def test_ordinary_adr_scenarios_keep_the_default_timeout(scenario):
    assert not any(mark.name == "timeout" for mark in getattr(scenario, "pytestmark", []))


def test_owned_hub_dps_link_lifecycle_includes_bounded_recovery_and_cleanup():
    assert readiness.HUB_LINK_READINESS_TIMEOUT == readiness.LINK_READINESS_TIMEOUT == 240
    scenario = links.TestADRLinkLifecycle.test_adr_link_lifecycle
    markers = [mark for mark in getattr(scenario, "pytestmark", []) if mark.name == "timeout"]
    assert len(markers) == 1
    assert markers[0].args == (900 + 3 * readiness.LINK_READINESS_TIMEOUT,)
    assert markers[0].kwargs == {"func_only": False}


@pytest.mark.parametrize("scenario,expected", [
    (links.TestADRLinkSU.test_adr_link_su_lifecycle, 4500 + 3600 + 2 * 1200),
    (links.TestADRLinkSequentialAdd.test_adr_link_sequential_add, 900 + 1200),
])
def test_fresh_link_scenarios_reserve_native_recovery_without_consuming_cleanup_budget(scenario, expected):
    assert links._NATIVE_LINK_TIMEOUT == 1200
    assert links._NATIVE_LINK_INTERVAL == 10
    markers = [mark for mark in getattr(scenario, "pytestmark", []) if mark.name == "timeout"]
    assert len(markers) == 1
    assert markers[0].args == (expected,)
    assert markers[0].kwargs == {"func_only": False}
