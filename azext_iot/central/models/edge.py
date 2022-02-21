# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


class EdgeModule:
    def __init__(
        self,
        module: dict,
    ):
        self._module = module
        self.module_id = module.get("moduleId")
        self.is_system_module = module.get("isSystemModule")
        self.status_description = module.get("statusDescription")
        self.restart_policy = module.get("restartPolicy")
        self.twin_status = module.get("twinStatus")
        self.connection_state = module.get("connectionState")
        self.settings = module.get("settings")
        self.last_restart_time_utc = module.get("lastRestartTimeUtc")
        self.last_start_time_utc = module.get("lastStartTimeUtc")
        self.last_exit_time_utc = module.get("lastExitTimeUtc")
        self.exit_code = module.get("exitCode")
