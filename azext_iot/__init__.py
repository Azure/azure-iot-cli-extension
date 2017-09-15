# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import azext_iot._help  # pylint: disable=unused-import


def load_params(_):
    import azext_iot._params  # pylint: disable=redefined-outer-name, unused-variable


def load_commands():
    import azext_iot.commands  # pylint: disable=redefined-outer-name, unused-variable
