# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.util import CLIError


def execute_query(query, query_method, errors, top=None):
    payload = []
    headers = {}

    # Consider top == 0
    if top is not None:
        if top <= 0:
            raise CLIError('top must be > 0')

    try:
        if top:
            headers['x-ms-max-item-count'] = str(top)
        result, token = query_method(query, headers)
        payload.extend(result)
        while token:
            # In case requested count is > service max page size
            if top:
                pl = len(payload)
                if pl < top:
                    page = top - pl
                    headers['x-ms-max-item-count'] = str(page)
                else:
                    break
            headers['x-ms-continuation'] = token
            result, token = query_method(query, headers)
            payload.extend(result)
        return payload[:top] if top else payload
    except errors.ErrorDetailsException as e:
        raise CLIError(e)
