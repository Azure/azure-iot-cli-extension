# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.util import CLIError
from azext_iot.assets.user_messages import error_param_top_out_of_bounds


def _execute_query(query_args, query_method, top=None):
    payload = []
    headers = {"Cache-Control": "no-cache, must-revalidate"}

    if top:
        headers["x-ms-max-item-count"] = str(top)

    result = query_method(*query_args, custom_headers=headers, raw=True)
    token = result.response.headers.get("x-ms-continuation")

    payload.extend(result.response.json())
    while token:
        # In case requested count is > service max page size
        if top:
            pl = len(payload)
            if pl < top:
                page = top - pl
                headers["x-ms-max-item-count"] = str(page)
            else:
                break
        headers["x-ms-continuation"] = token
        result = query_method(*query_args, custom_headers=headers, raw=True)
        token = result.response.headers.get("x-ms-continuation")
        payload.extend(result.response.json())
    return payload[:top] if top else payload


def _process_top(top, upper_limit=None):
    # Consider top == 0
    if not top and top != 0:
        return None
    if top == -1 and not upper_limit:
        return None
    if top <= 0 or (upper_limit and top > upper_limit):
        raise CLIError(error_param_top_out_of_bounds(upper_limit))
    return int(top)
