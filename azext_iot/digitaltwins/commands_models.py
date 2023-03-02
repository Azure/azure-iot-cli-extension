# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.digitaltwins.providers.model import ModelProvider
from azext_iot.digitaltwins.common import ADTModelCreateFailurePolicy
from knack.log import get_logger

logger = get_logger(__name__)


def add_models(
    cmd, name_or_hostname, models=None, from_directory=None,
    resource_group_name=None, failure_policy=ADTModelCreateFailurePolicy.ROLLBACK.value,
    max_models_per_batch=30
):
    model_provider = ModelProvider(cmd=cmd, name=name_or_hostname, rg=resource_group_name)
    logger.debug("Received models input: %s", models)
    return model_provider.add(
        models=models,
        from_directory=from_directory,
        failure_policy=failure_policy,
        max_models_per_batch=max_models_per_batch)


def show_model(cmd, name_or_hostname, model_id, definition=False, resource_group_name=None):
    model_provider = ModelProvider(cmd=cmd, name=name_or_hostname, rg=resource_group_name)
    return model_provider.get(id=model_id, get_definition=definition)


def list_models(
    cmd, name_or_hostname, definition=False, dependencies_for=None, resource_group_name=None
):
    model_provider = ModelProvider(cmd=cmd, name=name_or_hostname, rg=resource_group_name)
    return model_provider.list(
        get_definition=definition, dependencies_for=dependencies_for
    )


def update_model(cmd, name_or_hostname, model_id, decommission=None, resource_group_name=None):
    if decommission is None:
        logger.info("No update arguments provided. Nothing to update.")
        return

    model_provider = ModelProvider(cmd=cmd, name=name_or_hostname, rg=resource_group_name)
    return model_provider.update(id=model_id, decommission=decommission,)


def delete_model(cmd, name_or_hostname, model_id, resource_group_name=None):
    model_provider = ModelProvider(cmd=cmd, name=name_or_hostname, rg=resource_group_name)
    return model_provider.delete(id=model_id)


def delete_all_models(cmd, name_or_hostname, resource_group_name=None):
    model_provider = ModelProvider(cmd=cmd, name=name_or_hostname, rg=resource_group_name)
    return model_provider.delete_all()
