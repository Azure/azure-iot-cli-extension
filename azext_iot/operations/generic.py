# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
import pdb
from knack.util import CLIError
from azext_iot.assets.user_messages import ERROR_PARAM_TOP_OUT_OF_BOUNDS


def _execute_query(query, query_method, top=None):
    payload = []
    x_ms_max_item_count = top

    result, token = query_method(query, x_ms_max_item_count)
    payload.extend(result)
    while token:
        # In case requested count is > service max page size
        if top:
            pl = len(payload)
            if pl < top:
                page = top - pl
                x_ms_max_item_count = page
            else:
                break
        x_ms_continuation = token
        result, token = query_method(query, x_ms_max_item_count, x_ms_continuation)
        payload.extend(result)
    return payload[:top] if top else payload


def _process_top(top, upper_limit=None):
    # Consider top == 0
    if not top and top != 0:
        return None
    if top == -1 and not upper_limit:
        return None
    if top <= 0 or (upper_limit and top > upper_limit):
        raise CLIError(ERROR_PARAM_TOP_OUT_OF_BOUNDS(upper_limit))
    return int(top)
