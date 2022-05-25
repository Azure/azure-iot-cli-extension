# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
import sys
from azext_iot.common.utility import ensure_azure_namespace_path
from knack.log import get_logger


logger = get_logger(__name__)


def reload_modules() -> None:
    from azure.cli.core.extension import get_extension_path
    from azext_iot.constants import EXTENSION_NAME
    import importlib

    ext_path = get_extension_path(EXTENSION_NAME)

    ext_azure_dir = os.path.join(ext_path, "azure")
    if not os.path.isdir(ext_azure_dir):
        return

    ensure_azure_namespace_path()
    mods_for_reload = ["azure.core", "azure.core.utils", "azure.mgmt", "azure.mgmt.core"]
    mods_for_del = ["azure.core.utils._utils"]

    for mod in mods_for_del:
        if mod in sys.modules:
            del sys.modules[mod]

    # Reload modules with best attempt
    for mod in mods_for_reload:
        try:
            if mod in sys.modules:
                importlib.reload(sys.modules[mod])
        except Exception as e:
            logger.warning("Failed to reload module: %s, error: %s", mod, str(e))
