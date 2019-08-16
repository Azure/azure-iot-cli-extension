# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Unpublished works.
# --------------------------------------------------------------------------------------------

import json
from os.path import exists
from knack.log import get_logger
from knack.util import CLIError
from azext_iot.common.shared import SdkType, PnPModelType
from azext_iot.common._azure import get_iot_pnp_connection_string
from azext_iot.pnp_sdk.models import SearchOptions
from azext_iot._factory import _bind_sdk
from azext_iot._constants import PNP_API_VERSION, PNP_ENDPOINT
from azext_iot.common.utility import (unpack_pnp_http_error,
                                      get_sas_token,
                                      shell_safe_json_parse)
from azure.cli.core.util import read_file_content

logger = get_logger(__name__)


def iot_pnp_interface_publish(cmd, interface, repo_endpoint=PNP_ENDPOINT, repo_id=None, login=None):
    _validate_repository(repo_id, login)
    model_list = _iot_pnp_model_list(cmd, repo_endpoint, repo_id, interface, PnPModelType.interface,
                                     -1, login=login)
    if model_list and model_list[0].urn_id == interface:
        etag = model_list[0].etag
    else:
        raise CLIError('No PnP Model definition found for @id "{}"'.format(interface))

    target_interface = _iot_pnp_model_show(cmd, repo_endpoint, repo_id,
                                           interface, False, PnPModelType.interface, login=login)

    return _iot_pnp_model_publish(cmd, repo_endpoint, repo_id, interface, target_interface,
                                  etag, login=login)


def iot_pnp_interface_create(cmd, interface_definition, repo_endpoint=PNP_ENDPOINT, repo_id=None, login=None):
    _validate_repository(repo_id, login)
    return _iot_pnp_model_create_or_update(cmd, repo_endpoint, repo_id, interface_definition,
                                           PnPModelType.interface, False, login=login)


def iot_pnp_interface_update(cmd, interface_definition, repo_endpoint=PNP_ENDPOINT, repo_id=None, login=None):
    _validate_repository(repo_id, login)
    return _iot_pnp_model_create_or_update(cmd, repo_endpoint, repo_id, interface_definition,
                                           PnPModelType.interface, True, login=login)


def iot_pnp_interface_show(cmd, interface, repo_endpoint=PNP_ENDPOINT, repo_id=None, login=None):
    return _iot_pnp_model_show(cmd, repo_endpoint, repo_id,
                               interface, False, PnPModelType.interface, login=login)


def iot_pnp_interface_list(cmd, repo_endpoint=PNP_ENDPOINT, repo_id=None, search_string=None,
                           top=1000, login=None):
    return _iot_pnp_model_list(cmd, repo_endpoint, repo_id,
                               search_string, PnPModelType.interface,
                               top, login=login)


def iot_pnp_interface_delete(cmd, interface, repo_endpoint=PNP_ENDPOINT, repo_id=None, login=None):
    _validate_repository(repo_id, login)
    return _iot_pnp_model_delete(cmd, repo_endpoint, repo_id, interface, login)


def iot_pnp_model_publish(cmd, model, repo_endpoint=PNP_ENDPOINT, repo_id=None, login=None):
    _validate_repository(repo_id, login)
    model_list = _iot_pnp_model_list(cmd, repo_endpoint, repo_id, model, PnPModelType.capabilityModel,
                                     -1, login=login)
    if model_list and model_list[0].urn_id == model:
        etag = model_list[0].etag
    else:
        raise CLIError('No PnP Model definition found for @id "{}"'.format(model))

    target_model = _iot_pnp_model_show(cmd, repo_endpoint, repo_id,
                                       model, False, PnPModelType.capabilityModel, login=login)
    return _iot_pnp_model_publish(cmd, repo_endpoint, repo_id, model, target_model,
                                  etag, login=login)


def iot_pnp_model_create(cmd, model_definition, repo_endpoint=PNP_ENDPOINT, repo_id=None, login=None):
    _validate_repository(repo_id, login)
    return _iot_pnp_model_create_or_update(cmd, repo_endpoint, repo_id, model_definition,
                                           PnPModelType.capabilityModel, False, login=login)


def iot_pnp_model_update(cmd, model_definition, repo_endpoint=PNP_ENDPOINT, repo_id=None, login=None):
    _validate_repository(repo_id, login)
    return _iot_pnp_model_create_or_update(cmd, repo_endpoint, repo_id, model_definition,
                                           PnPModelType.capabilityModel, True, login=login)


def iot_pnp_model_show(cmd, model, repo_endpoint=PNP_ENDPOINT, repo_id=None, expand=False, login=None):
    return _iot_pnp_model_show(cmd, repo_endpoint, repo_id,
                               model, expand, PnPModelType.capabilityModel, login=login)


def iot_pnp_model_list(cmd, repo_endpoint=PNP_ENDPOINT, repo_id=None, search_string=None,
                       top=1000, login=None):
    return _iot_pnp_model_list(cmd, repo_endpoint, repo_id,
                               search_string, PnPModelType.capabilityModel,
                               top, login=login)


def iot_pnp_model_delete(cmd, model, repo_endpoint=PNP_ENDPOINT, repo_id=None, login=None):
    _validate_repository(repo_id, login)
    return _iot_pnp_model_delete(cmd, repo_endpoint, repo_id, model, login)


def _iot_pnp_model_publish(cmd, endpoint, repository, model_id, model_def, etag, login):

    target = get_iot_pnp_connection_string(cmd, endpoint, repository, login=login)
    pnp_sdk, errors = _bind_sdk(target, SdkType.pnp_sdk)

    contents = json.loads(json.dumps(model_def, separators=(',', ':'), indent=2))
    try:
        headers = get_sas_token(target)
        return pnp_sdk.create_or_update_model(model_id,
                                              api_version=PNP_API_VERSION,
                                              content=contents,
                                              if_match=etag,
                                              custom_headers=headers)
    except errors.HttpOperationError as e:
        raise CLIError(unpack_pnp_http_error(e))


def _iot_pnp_model_create_or_update(cmd, endpoint, repository, model_def, pnpModelType, is_update, login):

    target = get_iot_pnp_connection_string(cmd, endpoint, repository, login=login)
    pnp_sdk, errors = _bind_sdk(target, SdkType.pnp_sdk)
    etag = None
    model_def = _validate_model_definition(model_def)
    model_id = model_def.get('@id')
    if not model_id:
        raise CLIError('PnP Model definition requires @id! Please include @id and try again.')

    if is_update:
        model_list = _iot_pnp_model_list(cmd, endpoint, repository, model_id, pnpModelType,
                                         -1, login=login)
        if model_list and model_list[0].urn_id == model_id:
            etag = model_list[0].etag
        else:
            raise CLIError('No PnP Model definition found for @id "{}"'.format(model_id))

    contents = json.loads(json.dumps(model_def, separators=(',', ':'), indent=2))
    try:
        headers = get_sas_token(target)
        return pnp_sdk.create_or_update_model(model_id,
                                              api_version=PNP_API_VERSION,
                                              content=contents,
                                              repository_id=target.get('repository_id', None),
                                              if_match=etag,
                                              custom_headers=headers)
    except errors.HttpOperationError as e:
        raise CLIError(unpack_pnp_http_error(e))


def _iot_pnp_model_show(cmd, endpoint, repository, model_id, expand, pnpModelType, login):
    target = get_iot_pnp_connection_string(cmd, endpoint, repository, login=login)
    pnp_sdk, errors = _bind_sdk(target, SdkType.pnp_sdk)
    try:
        headers = get_sas_token(target)
        result = pnp_sdk.get_model(model_id, api_version=PNP_API_VERSION,
                                   repository_id=target.get('repository_id', None),
                                   custom_headers=headers,
                                   expand=expand)

        if not result or result["@type"].lower() != pnpModelType.value.lower():
            raise CLIError('PnP Model definition for "{}", not found.'.format(model_id))

        return result
    except errors.HttpOperationError as e:
        raise CLIError(unpack_pnp_http_error(e))


def _iot_pnp_model_list(cmd, endpoint, repository, search_string,
                        pnpModelType, top, login):
    target = get_iot_pnp_connection_string(cmd, endpoint, repository, login=login)

    pnp_sdk, errors = _bind_sdk(target, SdkType.pnp_sdk)
    try:
        headers = get_sas_token(target)
        search_options = SearchOptions(search_keyword=search_string,
                                       model_filter_type=pnpModelType.value)
        if top > 0:
            search_options.page_size = top

        result = pnp_sdk.search(search_options, api_version=PNP_API_VERSION,
                                repository_id=target.get('repository_id', None),
                                custom_headers=headers)
        return result.results
    except errors.HttpOperationError as e:
        raise CLIError(unpack_pnp_http_error(e))


def _iot_pnp_model_delete(cmd, endpoint, repository, model_id, login):
    target = get_iot_pnp_connection_string(cmd, endpoint, repository, login=login)

    pnp_sdk, errors = _bind_sdk(target, SdkType.pnp_sdk)
    try:
        headers = get_sas_token(target)
        return pnp_sdk.delete_model(model_id,
                                    repository_id=target.get('repository_id', None),
                                    api_version=PNP_API_VERSION,
                                    custom_headers=headers)
    except errors.HttpOperationError as e:
        raise CLIError(unpack_pnp_http_error(e))


def _looks_like_file(element):
    element = element.lower()
    if element.endswith(('.txt', '.json', '.md', '.rst', '.doc', '.docx')):
        return True
    return False


def _validate_model_definition(model_def):
    if exists(model_def):
        model_def = str(read_file_content(model_def))
    else:
        logger.info('Definition not from file path or incorrect path given.')

    try:
        return shell_safe_json_parse(model_def)
    except ValueError as e:
        logger.debug('Received definition: %s', model_def)
        if _looks_like_file(model_def):
            raise CLIError('The definition content looks like its from a file. Please ensure the path is correct.')
        raise CLIError('Malformed capability model definition. '
                       'Use --debug to see what was received. Error details: {}'.format(e))


def _validate_repository(repo_id, login):
    if not login and not repo_id:
        raise CLIError('Please provide the model repository\'s repositoryId (via the \'--repo-id\' or \'-r\' parameter)'
                       ' and endpoint (via the \'--endpoint\' or \'-e\' parameter) or model repository\'s connection'
                       ' string via --login...')
