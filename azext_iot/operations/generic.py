# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Optional
from azure.cli.core.azclierror import InvalidArgumentValueError
from azext_iot.assets.user_messages import error_param_top_out_of_bounds

from datetime import datetime

def _execute_query(query_args, query_method, top: Optional[int] = None):
    payload = []
    headers = {"Cache-Control": "no-cache, must-revalidate"}

    if top:
        headers["x-ms-max-item-count"] = str(top)
    print(headers)
    start = datetime.now()
    print(start)
    result = query_method(*query_args, custom_headers=headers, raw=True)
    token = result.response.headers.get("x-ms-continuation")
    new_time = datetime.now()
    print(f"page 0 took {(new_time - start).total_seconds()} seconds.")
    payload.extend(result.response.json())

    i = 0
    while token:
        old_time = new_time
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
        new_time = datetime.now()
        i += 1
        print(f"page {i} took {(new_time - old_time).total_seconds()} seconds.")
    print(f"total time {(datetime.now() - start).total_seconds()} seconds")
    return
    return payload[:top] if top else payload


def _process_top(top: int, upper_limit: Optional[int] = None):
    # Consider top == 0
    if not top and top != 0:
        return None
    if top == -1 and not upper_limit:
        return None
    if top <= 0 or (upper_limit and top > upper_limit):
        raise InvalidArgumentValueError(error_param_top_out_of_bounds(upper_limit))
    return int(top)
