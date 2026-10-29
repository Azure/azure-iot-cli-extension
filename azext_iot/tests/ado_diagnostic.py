# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Explicitly invoked offline diagnostic; never collected by the normal test suite."""

import os

import pytest


def test_always_passes():
    assert os.environ["azext_iot_ado_diagnostic_attempt"]


@pytest.mark.parametrize("case", ["normal", "retry-target"])
def test_example(case):
    assert case != "retry-target" or os.environ["azext_iot_ado_diagnostic_attempt"] != "1", (
        "Intentional first-attempt assertion failure in the offline retry diagnostic."
    )
