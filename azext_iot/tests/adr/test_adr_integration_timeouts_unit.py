# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest

from azext_iot.tests.adr import _helpers as helpers
from azext_iot.tests.adr import test_adr_certificate_authority_int as ca
from azext_iot.tests.adr import test_adr_link_int as links
from azext_iot.tests.adr import test_adr_update_instance_int as instances


@pytest.mark.parametrize("scenario", [
    instances.TestADRUpdateInstanceLifecycle.test_update_instance_lifecycle,
    links.TestADRLinkSU.test_adr_link_su_lifecycle,
])
def test_cold_su_scenarios_include_existing_readiness_and_cleanup_budgets(scenario):
    readiness = helpers.SU_PROVISIONING_MAX_POLLS * helpers.SU_PROVISIONING_POLL_INTERVAL
    assert readiness == 3600
    assert helpers.SU_LIFECYCLE_TIMEOUT == readiness + 900
    markers = [mark for mark in getattr(scenario, "pytestmark", []) if mark.name == "timeout"]
    assert len(markers) == 1
    assert markers[0].args == (4500,)
    assert markers[0].kwargs == {"func_only": False}


@pytest.mark.parametrize("scenario", [
    instances.TestADRUpdateInstanceValidation.test_update_instance_validation_negatives,
    links.TestADRLinkLifecycle.test_adr_link_lifecycle,
    links.TestADRLinkBundledAdd.test_adr_link_bundled_add,
    ca.TestADRCertificateAuthorityLifecycle.test_adr_certificate_authority_lifecycle,
])
def test_ordinary_adr_scenarios_keep_the_default_timeout(scenario):
    assert not any(mark.name == "timeout" for mark in getattr(scenario, "pytestmark", []))
