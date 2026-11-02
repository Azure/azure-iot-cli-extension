# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
import sys
import types

import azext_iot.deviceupdate.providers.loaders as subject


def test_reload_modules_no_ext_path(mocker):
    mocker.patch("azure.cli.core.extension.get_extension_path", return_value=None)
    # Should simply return without error.
    subject.reload_modules()


def test_reload_modules_no_azure_dir(mocker, tmp_path):
    mocker.patch("azure.cli.core.extension.get_extension_path", return_value=str(tmp_path))
    # No "azure" subdirectory -> early return.
    subject.reload_modules()


def test_reload_modules_init_internal_failure_logs_warning(mocker, tmp_path):
    """When init_internal_azure_core raises, the error is caught and logged."""
    ext_path = str(tmp_path)
    ext_azure_dir = os.path.join(ext_path, "azure")
    os.makedirs(ext_azure_dir)

    mocker.patch("azure.cli.core.extension.get_extension_path", return_value=ext_path)
    mocker.patch.object(subject, "ensure_azure_namespace_path")
    mocker.patch.object(
        subject, "init_internal_azure_core", side_effect=Exception("boom")
    )
    warning = mocker.patch.object(subject.logger, "warning")

    # Should not raise; the failure is swallowed and logged.
    subject.reload_modules()

    assert any(
        "Failed to build internal module cache" in str(call.args[0])
        for call in warning.call_args_list
    )


def test_reload_modules_full(mocker, tmp_path):
    ext_path = str(tmp_path)
    ext_azure_dir = os.path.join(ext_path, "azure")
    core_dir = os.path.join(ext_azure_dir, "core")
    os.makedirs(core_dir)
    # Minimal azure.core package layout so init_internal_azure_core can resolve specs.
    with open(os.path.join(core_dir, "__init__.py"), "w", encoding="utf-8"):
        pass
    with open(os.path.join(core_dir, "exceptions.py"), "w", encoding="utf-8"):
        pass

    mocker.patch("azure.cli.core.extension.get_extension_path", return_value=ext_path)
    mocker.patch.object(subject, "ensure_azure_namespace_path")

    outside = types.ModuleType("msrest")
    outside.__path__ = ["/some/outside/path"]

    inside = types.ModuleType("azure.core")
    inside.__path__ = [os.path.join(ext_azure_dir, "core")]

    utils = types.ModuleType("azure.core.utils")
    utils.__path__ = ["/some/outside/path"]

    prereq = types.ModuleType("azure.core.utils._utils")

    fake_modules = {
        "msrest": outside,
        "azure.core": inside,
        "azure.core.utils": utils,
        "azure.core.utils._utils": prereq,
    }
    mocker.patch.dict(sys.modules, fake_modules)

    # Ensure azure.mgmt.core is absent to exercise the "not in sys.modules" branch.
    saved_mgmt_core = sys.modules.pop("azure.mgmt.core", None)
    from azext_iot.constants import INTERNAL_AZURE_CORE_NAMESPACE
    try:
        subject.reload_modules()
        # init_internal_azure_core registered the internal namespace.
        assert INTERNAL_AZURE_CORE_NAMESPACE in sys.modules
    finally:
        if saved_mgmt_core is not None:
            sys.modules["azure.mgmt.core"] = saved_mgmt_core
        sys.modules.pop(INTERNAL_AZURE_CORE_NAMESPACE, None)
        sys.modules.pop(f"{INTERNAL_AZURE_CORE_NAMESPACE}.exceptions", None)
