# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.digitaltwins.common import ADT_CREATE_RETRY_AFTER, ProvisioningStateType
from knack.log import get_logger

logger = get_logger(__name__)


# Experimental
def accumulate_result(
    method,
    token_name="continuationToken",
    token_arg_name="continuation_token",
    values_name="items",
    **kwargs
):
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
        return text[len(prefix) :]
    return text


def generic_check_state(lro, show_cmd, max_retires):
    """
    Refresh the instance from the LRO poller until the refresh limit or the instance
    has finished creating.
    """
    from time import sleep
    instance = lro.resource().as_dict()
    state = _get_provisioning_state(instance)
    retries = 0
    while (state and state.lower() not in ProvisioningStateType.FINISHED.value) and retries < max_retires:
        retries += 1
        sleep(int(lro._response.headers.get('retry-after', ADT_CREATE_RETRY_AFTER)))
        lro.update_status()
        instance = lro.resource().as_dict()
        state = _get_provisioning_state(instance)
    if state and state.lower() not in ProvisioningStateType.FINISHED.value:
        logger.warning(
            "The resource has been created and has not finished provisioning. Please monitor the status of "
            f"the created instance using `{show_cmd}`."
        )


def _get_provisioning_state(instance):
    """Return the provisioning state from the instance result if present."""
    if instance.get('provisioning_state'):
        return instance.get('provisioning_state')
    elif instance.get('properties'):
        return instance.get('properties').get('provisioning_state')
    else:
        return
