# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


import pytest

from azext_iot.tests.adr import test_adr_link_int as subject


@pytest.mark.parametrize("scenario", [
    subject.TestADRLinkSequentialAdd.test_adr_link_sequential_add,

])
def test_fresh_link_scenarios_do_not_import_fixture_service_role_recovery(scenario):
    import inspect

    source = inspect.getsource(scenario)
    assert ".ensure(" not in source and ".ensure_many(" not in source
    assert "_ROLE_SETTLE_SECONDS" not in source
    assert "link_dps_with_readiness(" not in source and "link_hub_with_readiness(" not in source
    assert "_NATIVE_LINK_OPTIONS" in source
