# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
from azext_iot.digitaltwins.providers.base import (
    DigitalTwinsProvider,
    ErrorResponseException,
)
from azext_iot.digitaltwins.providers.model import ModelProvider
from azext_iot.common.utility import process_json_arg, unpack_msrest_error
from knack.log import get_logger
from knack.util import CLIError

logger = get_logger(__name__)


class TwinProvider(DigitalTwinsProvider):
    def __init__(self, cmd, name, rg=None):
        super(TwinProvider, self).__init__(
            cmd=cmd, name=name, rg=rg,
        )
        self.model_provider = ModelProvider(cmd=cmd, name=name, rg=rg)
        self.query_sdk = self.get_sdk().query
        self.twins_sdk = self.get_sdk().digital_twins

    def invoke_query(self, query, show_cost):
        from azext_iot.digitaltwins.providers.generic import accumulate_result

        accumulated_result, cost = accumulate_result(
            self.query_sdk.query_twins,
            values_name="value",
            token_name="continuationToken",
            token_arg_name="continuation_token",
            query=query,
        )

        query_result = {}
        query_result["result"] = accumulated_result
        if show_cost:
            query_result["cost"] = cost

        return query_result

    def create(self, twin_id, model_id, properties=None):
        target_model = self.model_provider.get(id=model_id)
        twin_request = {
            "$dtId": twin_id,
            "$metadata": {"$model": target_model["id"]},
        }

        if properties:
            properties = process_json_arg(
                content=properties, argument_name="properties"
            )
            twin_request.update(properties)

        logger.info("Twin payload %s", json.dumps(twin_request))

        try:
            return self.twins_sdk.add(id=twin_id, twin=twin_request, if_none_match="*")
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

    def get(self, twin_id):
        try:
            return self.twins_sdk.get_by_id(id=twin_id, raw=True).response.json()
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

    def update(self, twin_id, json_patch):
        json_patch = process_json_arg(content=json_patch, argument_name="json-patch")

        json_patch_collection = []
        if isinstance(json_patch, dict):
            json_patch_collection.append(json_patch)
        if isinstance(json_patch, list):
            json_patch_collection.extend(json_patch)

        logger.info("Patch payload %s", json.dumps(json_patch_collection))

        try:
            self.twins_sdk.update(
                id=twin_id, patch_document=json_patch_collection, if_match="*", raw=True
            )
            return self.get(twin_id=twin_id)
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

    def delete(self, twin_id):
        # Not a json response
        try:
            self.twins_sdk.delete(id=twin_id, if_match="*", raw=True)
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

    def add_relationship(
        self,
        twin_id,
        target_twin_id,
        relationship_id,
        relationship,
        properties=None,
    ):
        relationship_request = {
            "$targetId": target_twin_id,
            "$relationshipName": relationship,
        }

        if properties:
            properties = process_json_arg(
                content=properties, argument_name="properties"
            )
            relationship_request.update(properties)

        logger.info("Relationship payload %s", json.dumps(relationship_request))
        return self.twins_sdk.add_relationship(
            id=twin_id,
            relationship_id=relationship_id,
            relationship=relationship_request,
            if_none_match="*",
            raw=True,
        ).response.json()

    def get_relationship(self, twin_id, relationship_id):
        return self.twins_sdk.get_relationship_by_id(
            id=twin_id, relationship_id=relationship_id, raw=True
        ).response.json()

    def list_relationships(
        self, twin_id, incoming_relationships=False, relationship=None
    ):
        if not incoming_relationships:
            return self.twins_sdk.list_relationships(
                id=twin_id, relationship_name=relationship
            )

        incoming_pager = self.twins_sdk.list_incoming_relationships(id=twin_id)

        incoming_result = []
        try:
            while True:
                incoming_result.extend(incoming_pager.advance_page())
        except StopIteration:
            pass

        if relationship:
            incoming_result = [
                edge
                for edge in incoming_result
                if edge.relationship_name and edge.relationship_name == relationship
            ]

        return incoming_result

    def update_relationship(self, twin_id, relationship_id, json_patch):
        json_patch = process_json_arg(content=json_patch, argument_name="json-patch")

        json_patch_collection = []
        if isinstance(json_patch, dict):
            json_patch_collection.append(json_patch)
        if isinstance(json_patch, list):
            json_patch_collection.extend(json_patch)

        logger.info("Patch payload %s", json.dumps(json_patch_collection))

        try:
            self.twins_sdk.update_relationship(
                id=twin_id,
                relationship_id=relationship_id,
                patch_document=json_patch_collection,
                if_match="*",
            )
            return self.get_relationship(
                twin_id=twin_id, relationship_id=relationship_id
            )
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

    def delete_relationship(self, twin_id, relationship_id):
        try:
            self.twins_sdk.delete_relationship(
                id=twin_id, relationship_id=relationship_id, if_match="*"
            )
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

    def get_component(self, twin_id, component_path):
        return self.twins_sdk.get_component(
            id=twin_id, component_path=component_path, raw=True
        ).response.json()

    def update_component(self, twin_id, component_path, json_patch):
        json_patch = process_json_arg(content=json_patch, argument_name="json-patch")

        json_patch_collection = []
        if isinstance(json_patch, dict):
            json_patch_collection.append(json_patch)
        if isinstance(json_patch, list):
            json_patch_collection.extend(json_patch)

        logger.info("Patch payload %s", json.dumps(json_patch_collection))

        try:
            # TODO: API does not return response
            self.twins_sdk.update_component(
                id=twin_id,
                component_path=component_path,
                patch_document=json_patch_collection,
                if_match="*",
            )
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

    def send_telemetry(self, twin_id, telemetry=None, dt_id=None, component_path=None):
        from uuid import uuid4
        from datetime import datetime, timezone

        local_time = datetime.now(timezone.utc).astimezone()
        dt_timestamp = local_time.isoformat()

        telemetry_request = {}

        if telemetry:
            telemetry = process_json_arg(content=telemetry, argument_name="telemetry")
        else:
            telemetry = {}

        telemetry_request.update(telemetry)

        logger.info("Telemetry payload: {}".format(json.dumps(telemetry_request)))
        if not dt_id:
            dt_id = str(uuid4())

        if component_path:
            self.twins_sdk.send_component_telemetry(
                id=twin_id,
                message_id=dt_id,
                dt_timestamp=dt_timestamp,
                component_path=component_path,
                telemetry=telemetry_request,
            )

        self.twins_sdk.send_telemetry(
            id=twin_id,
            message_id=dt_id,
            dt_timestamp=dt_timestamp,
            telemetry=telemetry_request,
        )
