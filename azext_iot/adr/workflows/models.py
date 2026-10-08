# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


STATE_SATISFIED = "Satisfied"
STATE_PLANNED = "Planned"
STATE_MANUAL = "Manual"
STATE_BLOCKED = "Blocked"
STATE_SUCCEEDED = "Succeeded"
STATE_FAILED = "Failed"
STATE_NOT_CONFIGURED = "NotConfigured"
STATE_WARNING = "Warning"


@dataclass(frozen=True)
class EndpointSpec:
    kind: str
    endpoint_name: str
    resource_id: str
    identity_type: str
    user_assigned_identity: Optional[str] = None
    availability: Optional[str] = None
    allocation_weight: Optional[int] = None


@dataclass(frozen=True)
class SetupRequest:
    namespace_name: str
    resource_group_name: str
    location: Optional[str] = None
    outbound_identity_type: Optional[str] = None
    outbound_user_assigned_identity: Optional[str] = None
    dps: Optional[EndpointSpec] = None
    hubs: Tuple[EndpointSpec, ...] = ()
    software_updates: Optional[EndpointSpec] = None
    create_update_instance: bool = False
    update_instance_name: Optional[str] = None
    skipped: Tuple[str, ...] = ()
    check_status: bool = False
    subscription_id: Optional[str] = None
    tags: Optional[Dict[str, str]] = None

    @property
    def requests_links(self) -> bool:
        return bool(self.dps or self.hubs or self.software_updates)


@dataclass
class PlanItem:
    item_id: str
    action: str
    target: str
    state: str
    message: str = ""
    command: str = ""
    dependencies: Tuple[str, ...] = ()
    details: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        result = {
            "id": self.item_id,
            "action": self.action,
            "target": self.target,
            "state": self.state,
        }
        if self.message:
            result["message"] = self.message
        if self.command:
            result["command"] = self.command
        if self.dependencies:
            result["dependencies"] = list(self.dependencies)
        if self.details:
            result["details"] = self.details
        return result


class WorkflowExecutionError(Exception):
    def __init__(self, error: Exception, result: Dict[str, Any]):
        super().__init__(str(error) or error.__class__.__name__)
        self.result = result


def workflow_result(
    command: str,
    state: str,
    namespace_name: str,
    resource_group_name: str,
    items: List[PlanItem],
) -> Dict[str, Any]:
    counts: Dict[str, int] = {}
    for item in items:
        counts[item.state] = counts.get(item.state, 0) + 1
    return {
        "command": command,
        "state": state,
        "namespace": namespace_name,
        "resourceGroup": resource_group_name,
        "summary": counts,
        "items": [item.as_dict() for item in items],
    }
