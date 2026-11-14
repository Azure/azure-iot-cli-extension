# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Own ADU/ADR fixture resources only in explicitly enabled current ADO attempts."""

import os

from azext_iot.tests import _owned_resources as owned


def pytest_configure(config):
    journal = owned.activate(os.environ[owned.ENV])
    observer = owned.Observer(journal, owned.Arm(journal))
    observer.install()
    config.add_cleanup(observer.uninstall)
