# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.pnp.providers import (
    PnPModelRepositoryApiManager,
    CloudError,
)
from azext_iot.pnp.common import ModelState
from azext_iot.common.utility import unpack_msrest_error
from knack.util import CLIError


class ModelApiProvider(PnPModelRepositoryApiManager):
    def __init__(self, cmd, pnp_dns_suffix=None):
        super(ModelApiProvider, self).__init__(cmd=cmd)
        self.mgmt_sdk = self.get_mgmt_sdk(pnp_dns_suffix)

    def get_model(self, model_id, expand=False):
        try:
            return self.mgmt_sdk.get_model_async(
                model_id=model_id, expand=expand, raw=True
            ).response.json()
        except CloudError as e:
            raise CLIError(unpack_msrest_error(e))

    def create_model(
        self, model_id, json_ld_model,
    ):
        try:
            return self.mgmt_sdk.create_or_update_async(
                model_id=model_id,
                json_ld_model=json_ld_model,
                x_ms_model_state=ModelState.created.value,
                raw=True,
            ).response.json()
        except CloudError as e:
            raise CLIError(unpack_msrest_error(e))

    def publish_model(
        self, model_id,
    ):
        try:
            model_response = self.mgmt_sdk.get_model_async(model_id, raw=True)
            etag = model_response.response.headers.get("eTag")
            if not etag:
                raise CLIError(
                    "No model found with @id `{}` to publish".format(model_id)
                )
            etag = etag.replace('\\"', "")
            return self.mgmt_sdk.create_or_update_async(
                model_id=model_id,
                update_metadata=True,
                if_match=etag,
                x_ms_model_state=ModelState.listed.value,
                raw=True,
            ).response.json()
        except CloudError as e:
            raise CLIError(unpack_msrest_error(e))

    def search_models(
        self, search_options, shared_models_only=None, top=None,
    ):
        try:
            payload = []
            headers = {"Cache-Control": "no-cache, must-revalidate"}

            result = self.mgmt_sdk.search_models_async(
                model_search_options=search_options,
                x_ms_show_shared_models_only=shared_models_only,
                custom_headers=headers,
                raw=True,
            )

            payload.extend(result.response.json())

            return payload[:top] if top else payload
        except CloudError as e:
            raise CLIError(unpack_msrest_error(e))

    def validate_models(self, models=None, validate_dependencies=None):
        try:
            return self.mgmt_sdk.are_valid_models(
                json_ld_models=models, validate_dependencies=validate_dependencies,
            )
        except CloudError as e:
            raise CLIError(unpack_msrest_error(e))
