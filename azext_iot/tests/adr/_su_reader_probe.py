# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Opt-in, owned-resource experiment; never production caller authorization."""

from urllib.parse import urlsplit

from azure.core.exceptions import HttpResponseError
from msrestazure.tools import parse_resource_id

from azext_iot.tests.adr._log import LogKind, _log


class SUReaderProbe:
    """Try discovery without a fixture Reader grant; repeat once only after a data-plane GET 403."""

    def __init__(self, scenario, caller_id, resource_id, service_address):
        parsed = parse_resource_id(resource_id)
        assert ("su", parsed["name"], parsed["resource_group"]) in scenario._owned_resources, (
            "The Reader experiment requires a freshly owned Update Instance."
        )
        self.scenario = scenario
        self.caller_id = caller_id
        self.resource_id = resource_id
        assert isinstance(service_address, str) and service_address, "The Reader probe requires a service address."
        self.host = urlsplit(
            service_address if "://" in service_address else f"https://{service_address}"
        ).hostname
        assert self.host, "The Reader experiment requires the linked service address."
        self.assignment_id = None
        assignments = scenario.cmd(
            f"role assignment list --assignee-object-id {caller_id} --scope '{resource_id}' "
            "--include-inherited --include-groups --fill-principal-name false"
        ).get_output_in_json()
        observed = [
            {key: assignment.get(key) for key in (
                "id", "principalId", "roleDefinitionId", "roleDefinitionName", "scope", "condition",
            )}
            for assignment in assignments
        ]
        _log(LogKind.RESULT, "SU Reader probe caller=%s target=%s inherited/group assignments=%s",
             caller_id, resource_id, observed)
        _log(LogKind.WARN, "Caller RBAC may already authorize discovery; a pass cannot prove Reader universally unnecessary.")

    def _invoke(self, command):
        phase = "after fixture Reader" if self.assignment_id else "without fixture Reader"
        try:
            result = self.scenario.cmd(command)
        except HttpResponseError as error:
            response = error.response
            request = getattr(response, "request", None)
            headers = getattr(response, "headers", None) or {}
            _log(
                LogKind.RESULT, "SU Reader probe %s: HTTP %s url=%s requestId=%s correlationId=%s",
                phase, error.status_code, getattr(request, "url", None),
                headers.get("x-ms-request-id"), headers.get("x-ms-correlation-request-id"),
            )
            raise
        _log(LogKind.RESULT, "SU Reader probe %s: command succeeded", phase)
        return result

    def cmd(self, command):
        try:
            return self._invoke(command)
        except HttpResponseError as error:
            response = error.response
            request = getattr(response, "request", None)
            if (
                self.assignment_id or error.status_code != 403
                or getattr(response, "status_code", None) != 403
                or getattr(request, "method", None) != "GET"
                or urlsplit(getattr(request, "url", "") or "").hostname != self.host
            ):
                raise
        # Only this one fresh owned target may receive the existing fixture role.
        self.assignment_id = self.scenario.assign_role(
            self.caller_id, "Device Update Reader", self.resource_id, assignee_type=None,
        )
        assert self.assignment_id, "The SU Reader probe could not establish its scoped fixture role."
        _log(LogKind.RESULT, "SU Reader probe fixture assignment=%s; repeating the identical command once",
             self.assignment_id)
        return self._invoke(command)
