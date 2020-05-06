# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from abc import ABC, abstractmethod

from azext_iot.monitor.parsers.issue import Severity


class AbstractBaseParser(ABC):
    def __init__(self, logger=None):
        super().__init__()

    @abstractmethod
    def write_logs(self, severity=Severity.info) -> None:
        raise NotImplementedError()

    @abstractmethod
    def parse_message(self, message, **kwargs) -> dict:
        raise NotImplementedError()

    @abstractmethod
    def parse_device_id(self, message) -> str:
        raise NotImplementedError()


class AbstractBaseEventsHandler(ABC):
    def __init__(self):
        super().__init__()

    @abstractmethod
    def parse_message(self, message):
        raise NotImplementedError()
