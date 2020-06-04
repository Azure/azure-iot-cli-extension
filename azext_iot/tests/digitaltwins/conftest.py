# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from azext_iot.digitaltwins.providers.resource import ResourceProvider


@pytest.fixture
def dt_rp(fixture_cmd2):
    rp = ResourceProvider(fixture_cmd2)
    yield rp
