# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.common.embedded_cli import EmbeddedCLI
from az_help import AzCliHelp

cli = EmbeddedCLI(help_cls=AzCliHelp)

cli.get_help("iot hub message-endpoint")

cli.get_help("iot hub message-endpoint show")