# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.common.embedded_cli import EmbeddedCLI
from knack.util import CLIError


class RbacProvider(object):
    def __init__(self):
        self.cli = EmbeddedCLI()

    def list_assignments(self, dt_scope, include_inherited=False, role_type=None):
        include_inherited_flag = ""
        filter_role_type = ""

        if include_inherited:
            include_inherited_flag = "--include-inherited"

        if role_type:
            filter_role_type = "--role '{}'".format(role_type)

        list_op = self.cli.invoke(
            "role assignment list --scope '{}' {} {}".format(
                dt_scope, filter_role_type, include_inherited_flag
            )
        )

        if not list_op.success():
            raise CLIError("Unable to determine assignments.")

        return list_op.as_json()

    def assign_role(self, dt_scope, assignee, role_type):
        assign_op = self.cli.invoke(
            "role assignment create --scope '{}' --role '{}' --assignee '{}'".format(
                dt_scope, role_type, assignee
            )
        )
        if not assign_op.success():
            raise CLIError("Unable to assign role.")

        return assign_op.as_json()

    def remove_role(self, dt_scope, assignee, role_type=None):
        filter_role_type = ""
        if role_type:
            filter_role_type = "--role '{}'".format(role_type)

        delete_op = self.cli.invoke(
            "role assignment delete --scope '{}' --assignee '{}' {}".format(
                dt_scope, assignee, filter_role_type
            )
        )
        if not delete_op.success():
            raise CLIError("Unable to remove role assignment.")
        return
