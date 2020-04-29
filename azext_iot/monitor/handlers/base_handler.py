# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from abc import ABC, abstractmethod


class AbstractBaseEventsHandler(ABC):
    def __init__(self):
        super().__init__()

    @abstractmethod
    def parse_message(self, message):
        pass
