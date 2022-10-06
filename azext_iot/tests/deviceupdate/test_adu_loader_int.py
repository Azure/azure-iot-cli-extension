# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
from azext_iot.deviceupdate.providers.loaders import reload_modules
from azext_iot.constants import INTERNAL_AZURE_CORE_NAMESPACE
from azure.cli.core.extension import get_extension_path
from azext_iot.constants import EXTENSION_NAME

ext_path = get_extension_path(EXTENSION_NAME)
ext_azure_core_dir = os.path.join(ext_path, "azure", "core")
ext_azure_core_utils_dir = os.path.join(ext_azure_core_dir, "utils")
ext_msrest_dir = os.path.join(ext_path, "msrest")


def test_adu_reload_modules():
    reload_modules()

    import azure
    import sys
    import msrest

    internal_core = sys.modules.get(INTERNAL_AZURE_CORE_NAMESPACE)
    assert internal_core
    assert internal_core.__name__ == "azure.core"
    assert internal_core.__path__ == [ext_azure_core_dir]
    assert internal_core.exceptions.__name__ == "azure.core.exceptions"
    assert internal_core.exceptions.__file__ == os.path.join(ext_azure_core_dir, "exceptions.py")

    assert azure.core.__name__ == "azure.core"
    assert azure.core.__path__ == [ext_azure_core_dir]

    assert azure.core.utils.__name__ == "azure.core.utils"
    assert azure.core.utils.__path__ == [ext_azure_core_utils_dir]

    assert msrest.__name__ == "msrest"
    assert msrest.__path__ == [ext_msrest_dir]
