# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest


@pytest.fixture(scope="session", autouse=True)
def _cleanup_dynamic_hub():
    """Only the external lease owner may clean up this cohort's parent resources."""
