# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Private distribution for preview customers
# Governed by license terms at https://aka.ms/iothub-certmgmt-privprev-license
# --------------------------------------------------------------------------------------------
import asyncio

from typing import List

from azext_iot.common._azure import get_iot_central_tokens
from azext_iot.monitor.models.target import Target
from azext_iot.monitor.builders._common import convert_token_to_target


def build_central_event_hub_targets(
    cmd, app_id, aad_token, central_dns_suffix
) -> List[Target]:
    event_loop = asyncio.get_event_loop()
    return event_loop.run_until_complete(
        _build_central_event_hub_targets_async(
            cmd, app_id, aad_token, central_dns_suffix
        )
    )


async def _build_central_event_hub_targets_async(
    cmd, app_id, aad_token, central_dns_suffix
):
    all_tokens = get_iot_central_tokens(cmd, app_id, aad_token, central_dns_suffix)
    targets = [await convert_token_to_target(token) for token in all_tokens.values()]

    return targets
