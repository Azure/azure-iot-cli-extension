# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.pnp.providers.model_repository_api import ModelApiProvider
from azext_iot.sdk.pnp.dataplane.models import ModelSearchOptions, ServiceError
from knack.util import CLIError
from azext_iot.common.utility import process_json_arg


def iot_pnp_model_show(cmd, model_id, expand=False):
    if not model_id:
        raise CLIError("Please provide a model id [-m, --model-id]")
    ap = ModelApiProvider(cmd)
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
):
    ap = ModelApiProvider(cmd)
    search_options = ModelSearchOptions(
        search_keyword=keyword,
        model_type=model_type,
        model_state=model_state,
        publisher_id=publisher_id,
        created_by=created_by,
    )

    return ap.search_models(search_options, shared, top)


def iot_pnp_model_create(cmd, model_id, model):
    if not model_id or not model:
        raise CLIError(
            "Please provide a model id [-m, --model-id] and a model definition [--model]"
        )
    ap = ModelApiProvider(cmd)
    model = process_json_arg(model, argument_name="model")
    is_valid = ap.validate_models([model], validate_dependencies=True)
    if isinstance(is_valid, ServiceError):
        raise CLIError("{}: {}".format(is_valid.code, is_valid.message))
    return ap.create_model(model_id, model)


def iot_pnp_model_publish(cmd, model_id):
    if not model_id:
        raise CLIError("Please provide a model id [-m, --model-id]")
    ap = ModelApiProvider(cmd)
    return ap.publish_model(model_id=model_id)
