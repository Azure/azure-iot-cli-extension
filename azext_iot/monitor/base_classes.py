# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Private distribution for preview customers
# Governed by license terms at https://aka.ms/iothub-certmgmt-privprev-license
# --------------------------------------------------------------------------------------------

from abc import ABC, abstractmethod


class AbstractBaseParser(ABC):
    def __init__(self):
        super().__init__()

    @abstractmethod
    def parse_message(self, message) -> dict:
        raise NotImplementedError()


class AbstractBaseEventsHandler(ABC):
    def __init__(self):
        super().__init__()

    @abstractmethod
    def parse_message(self, message):
        raise NotImplementedError()
