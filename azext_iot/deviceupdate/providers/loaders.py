# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
import sys
from azext_iot.common.utility import ensure_azure_namespace_path
from knack.log import get_logger
from typing import List


logger = get_logger(__name__)


def reload_modules() -> None:
    """
    Incremental fix for azure namespace package usage.

    Use to ensure shared azure namespace packages are being loaded from the
    azure-iot extension directory vs base Azure CLI. This is particularly important
    when both Azure CLI and the azure-iot extension have the same namespace package
    dependency but different version requirements.

    This needs to be executed before azure.* modules are imported.
    """

    from azure.cli.core.extension import get_extension_path
    from azext_iot.constants import EXTENSION_NAME
    import importlib

    ext_path = get_extension_path(EXTENSION_NAME)

    ext_azure_dir = os.path.join(ext_path, "azure")
    if not os.path.isdir(ext_azure_dir):
        return

    ensure_azure_namespace_path()

    def needs_reload(module_name: str) -> bool:
        if module_name in sys.modules:
            target_module = sys.modules.get(module_name)
            _reload = True
            if hasattr(target_module, "__path__"):
                for path in target_module.__path__:
                    if path.startswith(ext_azure_dir):
                        _reload = False
                        break
            return _reload
        return False

    def reload_module_state(module_name: str, remove_prereq: List[str] = None):
        if remove_prereq:
            for prereq in remove_prereq:
                if prereq in sys.modules:
                    del sys.modules[prereq]

        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    # This structure defines the target module for reload, and any prereq removals for a succesful reload.
    mods_for_reload = {"azure.core": [], "azure.core.utils": ["azure.core.utils._utils"], "azure.mgmt.core": []}

    # Import modules with best attempt
    for mod in mods_for_reload:
        try:
            if needs_reload(mod):
                reload_module_state(mod, mods_for_reload[mod])
        except Exception as e:
            logger.warning("Failed to reload module: %s, error: %s", mod, str(e))
