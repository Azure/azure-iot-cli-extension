# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


# Experimental - depends on consistency of APIs
def accumulate_result(method, token_name="continuationToken", token_arg_name="continuation_token", values_name="items", **kwargs):
    result_accumulator = []

    nextlink = None
    token_keyword = {token_arg_name: nextlink}

    # TODO: Genericize
    query_cost_sum = 0

    while True:
        response = method(raw=True, **token_keyword, **kwargs).response
        headers = response.headers
        if headers:
            query_charge = headers.get("query-charge")
            if query_charge:
                query_cost_sum = query_cost_sum + float(query_charge)

        result = response.json()
        if result and result.get(values_name):
            result_values = result.get(values_name)
            result_accumulator.extend(result_values)
            nextlink = result.get(token_name)
            if not nextlink:
                break
            token_keyword[token_arg_name] = nextlink
        else:
            break

    return result_accumulator, query_cost_sum


def remove_prefix(text, prefix):
    if text.startswith(prefix):
        return text[len(prefix):]
    return text
