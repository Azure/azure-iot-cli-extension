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


class TwinOptions():
    def __init__(self, if_match=None, if_none_match=None):
        self.if_match = if_match
        self.if_none_match = if_none_match
        self.traceparent = None
        self.tracestate = None


class TwinProvider(DigitalTwinsProvider):
    def __init__(self, cmd, name, rg=None):
        super(TwinProvider, self).__init__(
            cmd=cmd,
            name=name,
            rg=rg,
        )
        self.model_provider = ModelProvider(cmd=cmd, name=name, rg=rg)
        self.query_sdk = self.get_sdk().query
        self.twins_sdk = self.get_sdk().digital_twins

    def invoke_query(self, query, show_cost):
        from azext_iot.digitaltwins.providers.generic import accumulate_result

        try:
            accumulated_result, cost = accumulate_result(
                self.query_sdk.query_twins,
                values_name="value",
                token_name="continuationToken",
                token_arg_name="continuation_token",
                query=query,
            )
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

        query_result = {}
        query_result["result"] = accumulated_result
        if show_cost:
            query_result["cost"] = cost

        return query_result

    def create(self, twin_id, model_id, if_none_match=False, properties=None):
        twin_request = {
            "$dtId": twin_id,
            "$metadata": {"$model": model_id},
        }

        if properties:
            properties = process_json_arg(
                content=properties, argument_name="properties"
            )
            twin_request.update(properties)

        logger.info("Twin payload %s", json.dumps(twin_request))

        try:
            options = TwinOptions(if_none_match=("*" if if_none_match else None))
            return self.twins_sdk.add(id=twin_id, twin=twin_request, digital_twins_add_options=options)
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

    def get(self, twin_id):
        try:
            return self.twins_sdk.get_by_id(id=twin_id, raw=True).response.json()
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

    def update(self, twin_id, json_patch, etag=None):
        json_patch = process_json_arg(content=json_patch, argument_name="json-patch")

        json_patch_collection = []
        if isinstance(json_patch, dict):
            json_patch_collection.append(json_patch)
        if isinstance(json_patch, list):
            json_patch_collection.extend(json_patch)

        logger.info("Patch payload %s", json.dumps(json_patch_collection))

        try:
            options = TwinOptions(if_match=(etag if etag else "*"))
            self.twins_sdk.update(
                id=twin_id, patch_document=json_patch_collection, digital_twins_update_options=options, raw=True
            )
            return self.get(twin_id=twin_id)
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

    def delete(self, twin_id=None, delete_all=False, etag=None):
        if delete_all:
            # need to get all twins
            query = "select * from digitaltwins"
            twins = self.invoke_query(query=query, show_cost=False)["result"]

            # confirmation
            # logger.warn(f"This operation will delete all twins")
            # i = input(f"Delete all twins? (y/n)")
            # note that input will be really annoying to test
            if len(twins) == 0:
                print(f"Found {len(twins)} twins.")
                return

            i = input(f"Found {len(twins)} twin(s). Delete all? (y/n) ")
            if i.lower() != "y":
                return

            # go through and delete all
            options = TwinOptions(if_match=(etag if etag else "*"))
            print(twins)
            for twin in twins:
                try:
                    print("remove relationships")
                    self.delete_relationship(
                        twin_id=twin["$dtId"],
                        relationship_id="REMOVETHIS",
                        delete_all=True,
                        etag=etag,
                        skip=True
                    )
                    print("actual remove")
                    self.twins_sdk.delete(id=twin["$dtId"], digital_twins_delete_options=options, raw=True)
                    print("Deleted.")
                except ErrorResponseException as e:
                    logger.warn(f"Could not delete twin {twin['$dtId']}. The error is {unpack_msrest_error(e)}")
        elif twin_id:
            try:
                options = TwinOptions(if_match=(etag if etag else "*"))
                self.twins_sdk.delete(id=twin_id, digital_twins_delete_options=options, raw=True)
            except ErrorResponseException as e:
                raise CLIError(unpack_msrest_error(e))
        else:
            raise CLIError("Must provide twin id if not deleting all twins")

    def delete_all(self, etag=None):
        # need to get all twins
        query = "select * from digitaltwins"
        twins = self.invoke_query(query=query, show_cost=False)["result"]
        print(f"Found {len(twins)} twin(s).")

        # go through and delete all
        for twin in twins:
            try:
                self.delete_all_relationship(
                    twin_id=twin["$dtId"],
                    etag=etag,
                )
                self.delete(twin_id=twin["$dtId"], etag=etag)
            except CLIError as e:
                logger.warn(f"Could not delete twin {twin['$dtId']}. The error is {e}")

    def add_relationship(
        self,
        twin_id,
        target_twin_id,
        relationship_id,
        relationship,
        if_none_match=False,
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
        try:
            options = TwinOptions(if_none_match=("*" if if_none_match else None))
            return self.twins_sdk.add_relationship(
                id=twin_id,
                relationship_id=relationship_id,
                relationship=relationship_request,
                digital_twins_add_relationship_options=options,
                raw=True,
            ).response.json()
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

    def get_relationship(self, twin_id, relationship_id):
        try:
            return self.twins_sdk.get_relationship_by_id(
                id=twin_id, relationship_id=relationship_id, raw=True
            ).response.json()
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

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
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

        if relationship:
            incoming_result = [
                edge
                for edge in incoming_result
                if edge.relationship_name and edge.relationship_name == relationship
            ]

        return incoming_result

    def update_relationship(self, twin_id, relationship_id, json_patch, etag=None):
        json_patch = process_json_arg(content=json_patch, argument_name="json-patch")

        json_patch_collection = []
        if isinstance(json_patch, dict):
            json_patch_collection.append(json_patch)
        if isinstance(json_patch, list):
            json_patch_collection.extend(json_patch)

        logger.info("Patch payload %s", json.dumps(json_patch_collection))

        try:
            options = TwinOptions(if_match=(etag if etag else "*"))
            self.twins_sdk.update_relationship(
                id=twin_id,
                relationship_id=relationship_id,
                patch_document=json_patch_collection,
                digital_twins_update_relationship_options=options,
            )
            return self.get_relationship(
                twin_id=twin_id, relationship_id=relationship_id
            )
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

    def delete_relationship(self, twin_id, relationship_id=None, delete_all=False, etag=None, skip=False):
        if delete_all:
            relationships = self.list_relationships(twin_id, incoming_relationships=True)
            incoming_pager = self.list_relationships(twin_id)

            # relationships pager needs to be advanced to get relationships
            try:
                while True:
                    relationships.extend(incoming_pager.advance_page())
            except StopIteration:
                pass

            # confirmation for all. Skip for other functions that call this.
            if relationships == []:
                print(f"Found {len(relationships)} relationships associated with twin {twin_id}.")
                return

            if not skip:
                i = input(f"Found {len(relationships)} relationship(s) associated with twin {twin_id}. Delete all? (y/n) ")
                if i.lower() != 'y':
                    return

            options = TwinOptions(if_match=(etag if etag else "*"))
            for relationship in relationships:
                try:
                    if type(relationship) == dict:
                        self.twins_sdk.delete_relationship(
                            id=twin_id,
                            relationship_id=relationship['$relationshipId'],
                            digital_twins_delete_relationship_options=options
                        )
                    else:
                        self.twins_sdk.delete_relationship(
                            id=relationship.source_id,
                            relationship_id=relationship.relationship_id,
                            digital_twins_delete_relationship_options=options
                        )
                except ErrorResponseException as e:
                    logger.warn(f"Could not delete relationship {relationship}. The error is {unpack_msrest_error(e)}.")
        elif relationship_id:
            try:
                options = TwinOptions(if_match=(etag if etag else "*"))
                self.twins_sdk.delete_relationship(
                    id=twin_id, relationship_id=relationship_id, digital_twins_delete_relationship_options=options
                )
            except ErrorResponseException as e:
                raise CLIError(unpack_msrest_error(e))
        else:
            raise CLIError("Must provide relationship id if not deleting all relationships")

    def delete_all_relationship(self, twin_id, etag=None):
        relationships = self.list_relationships(twin_id, incoming_relationships=True)
        incoming_pager = self.list_relationships(twin_id)

        # relationships pager needs to be advanced to get relationships
        try:
            while True:
                relationships.extend(incoming_pager.advance_page())
        except StopIteration:
            pass

        print(f"Found {len(relationships)} relationship(s) associated with twin {twin_id}.")

        for relationship in relationships:
            try:
                if type(relationship) == dict:
                    self.delete_relationship(
                        twin_id=twin_id,
                        relationship_id=relationship['$relationshipId'],
                        etag=etag
                    )
                else:
                    self.delete_relationship(
                        twin_id=relationship.source_id,
                        relationship_id=relationship.relationship_id,
                        etag=etag
                    )
            except CLIError as e:
                logger.warn(f"Could not delete relationship {relationship}. The error is {e}.")

    def get_component(self, twin_id, component_path):
        try:
            return self.twins_sdk.get_component(
                id=twin_id, component_path=component_path, raw=True
            ).response.json()
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))

    def update_component(self, twin_id, component_path, json_patch, etag=None):
        json_patch = process_json_arg(content=json_patch, argument_name="json-patch")

        json_patch_collection = []
        if isinstance(json_patch, dict):
            json_patch_collection.append(json_patch)
        if isinstance(json_patch, list):
            json_patch_collection.extend(json_patch)

        logger.info("Patch payload %s", json.dumps(json_patch_collection))

        try:
            options = TwinOptions(if_match=(etag if etag else "*"))
            self.twins_sdk.update_component(
                id=twin_id,
                component_path=component_path,
                patch_document=json_patch_collection,
                digital_twins_update_component_options=options,
            )
            return self.get_component(twin_id=twin_id, component_path=component_path)
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

        try:
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
        except ErrorResponseException as e:
            raise CLIError(unpack_msrest_error(e))
