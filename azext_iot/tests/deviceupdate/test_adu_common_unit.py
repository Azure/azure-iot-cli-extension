# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.deviceupdate.common import get_cache_entry_name


def test_get_cache_entry_name():
    assert get_cache_entry_name("acct", "inst") == "acct_inst_importUpdate"
