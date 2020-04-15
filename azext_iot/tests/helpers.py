# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import os

from inspect import getsourcefile

from azext_iot.common.utility import read_file_content


def load_json(filename):
    os.chdir(os.path.dirname(os.path.abspath(getsourcefile(lambda: 0))))
    return json.loads(read_file_content(filename))
