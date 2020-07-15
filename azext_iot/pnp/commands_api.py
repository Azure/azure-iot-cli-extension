# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.pnp.providers.model_repository_api import ModelApiProvider
from azext_iot.sdk.pnp.dataplane.models import ModelSearchOptions
from knack.util import CLIError
from azext_iot.common.utility import process_json_arg
from azext_iot.operations.generic import _process_top


def iot_pnp_model_show(cmd, model_id, expand=False, pnp_dns_suffix=None):
    if not model_id:
        raise CLIError("Please provide a model id [--model-id]")
    ap = ModelApiProvider(cmd, pnp_dns_suffix)
    return ap.get_model(model_id, expand)


def iot_pnp_model_list(
    cmd,
    keyword=None,
    model_type=None,
    model_state=None,
    publisher_id=None,
    created_by=None,
    shared=False,
    top=None,
    pnp_dns_suffix=None,
):
    ap = ModelApiProvider(cmd, pnp_dns_suffix)
    search_options = ModelSearchOptions(
        search_keyword=keyword,
        model_type=model_type,
        model_state=model_state,
        publisher_id=publisher_id,
        created_by=created_by,
    )

    return ap.search_models(search_options, shared, _process_top(top))


def iot_pnp_model_create(cmd, model, pnp_dns_suffix=None):
    if not model:
        raise CLIError("Please provide a model definition [--model]")
    ap = ModelApiProvider(cmd, pnp_dns_suffix)
    model = process_json_arg(model, argument_name="model")
    model_id = model.get("@id")
    if not model_id:
        raise CLIError("Model is invalid - @id attribute required.")
    return ap.create_model(model_id, model)


def iot_pnp_model_publish(cmd, model_id, pnp_dns_suffix=None):
    if not model_id:
        raise CLIError("Please provide a model id [--model-id]")
    ap = ModelApiProvider(cmd, pnp_dns_suffix)
    return ap.publish_model(model_id=model_id)
