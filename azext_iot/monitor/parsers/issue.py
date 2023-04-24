# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import List
from azext_iot.monitor.utility import unicode_decode
from knack.log import get_logger

from azext_iot.monitor.models.enum import Severity

logger = get_logger(__name__)


class Issue:
    def __init__(self, severity: Severity, details: str, message, device_id=""):
        self.severity = severity
        self.details = details
        self.device_id = device_id
        self.message = None
        if message:
            message_body = next(message.get_data())
            self.message = unicode_decode(data=message_body, default="Failed to represent content in unicode format.")

        if not self.device_id:
            self.device_id = "Unknown"

    def log(self):
        to_log = "[{}] [DeviceId: {}] {}\n".format(
            self.severity.name.upper(), self.device_id, self.details
        )

        self._log(to_log)

    def _log(self, to_log: str):
        if self.severity == Severity.info:
            logger.info(to_log)

        if self.severity == Severity.warning:
            logger.warning(to_log)

        if self.severity == Severity.error:
            logger.error(to_log)

    def json_repr(self):
        json_repr = vars(self)
        json_repr["severity"] = self.severity.name
        return json_repr


class CentralIssue(Issue):
    def __init__(
        self, severity: Severity, details: str, message, device_id="", template_id=""
    ):
        super(CentralIssue, self).__init__(severity, details, message, device_id)
        self.template_id = template_id

        if not self.template_id:
            self.template_id = "Unknown"

    def log(self):
        to_log = "[{}] [DeviceId: {}] [TemplateId: {}] {}\n".format(
            self.severity.name.upper(), self.device_id, self.template_id, self.details
        )

        self._log(to_log)


class IssueHandler:
    def __init__(self):
        self._issues = []

    def add_issue(self, severity: Severity, details: str, message, device_id=""):
        issue = Issue(
            severity=severity, details=details, message=message, device_id=device_id
        )
        self._issues.append(issue)

    def add_central_issue(
        self, severity: Severity, details: str, message, device_id="", template_id=""
    ):
        issue = CentralIssue(
            severity=severity,
            details=details,
            message=message,
            device_id=device_id,
            template_id=template_id,
        )
        self._issues.append(issue)

    def get_all_issues(self) -> List[Issue]:
        return self._issues

    def get_issues_with_severity(self, severity: Severity) -> List[Issue]:
        """
        arguments:
            severity: Severity
        returns:
            all issues where severity equal specified severity

        example:
            issue_handler.get_issues_with_severity(Severity.info)
            returns all issues classified as "info"
        """
        return [issue for issue in self._issues if issue.severity == severity]

    def get_issues_with_minimum_severity(self, severity: Severity) -> List[Issue]:
        """
        arguments:
            severity: Severity
        returns:
            all issues where severity >= specified severity

        example:
            issue_handler.get_issues_with_minimum_severity(Severity.warning)
            returns all issues classified as "warning" and "error"
            "info" will not be included
        """
        return [issue for issue in self._issues if issue.severity >= severity]

    def get_issues_with_maximum_severity(self, severity: Severity) -> List[Issue]:
        """
        arguments:
            severity: Severity
        returns:
            all issues where severity <= specified severity

        example:
            issue_handler.get_issues_with_maximum_severity(Severity.warning)
            returns all issues classified as "warning" and "info"
            "error" will not be included
        """
        return [issue for issue in self._issues if issue.severity <= severity]
