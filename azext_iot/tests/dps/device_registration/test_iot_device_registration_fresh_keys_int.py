# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Each credential/endpoint cohort gets untouched service-generated credentials."""

import pytest

from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.dps.device_registration import register_fresh_generated_credential


@pytest.mark.parametrize("kind", ["individual", "group"])
@pytest.mark.parametrize("endpoint", ["configured", "global"])
@pytest.mark.parametrize("key_name", ["secondaryKey", "primaryKey"])
def test_fresh_registration_credential(provisioned_iot_dps_module, kind, endpoint, key_name, request):
    register_fresh_generated_credential(
        EmbeddedCLI(), provisioned_iot_dps_module, kind, key_name, request, endpoint=endpoint,
    )
