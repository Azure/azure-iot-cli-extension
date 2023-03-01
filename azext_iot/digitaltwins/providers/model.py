# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
from knack.log import get_logger
from azure.cli.core.azclierror import ForbiddenError, RequiredArgumentMissingError, InvalidArgumentValueError
from azext_iot.common.utility import process_json_arg, handle_service_exception, scantree
from azext_iot.digitaltwins.common import ADTModelCreateFailurePolicy
from azext_iot.digitaltwins.providers.base import DigitalTwinsProvider
from azext_iot.sdk.digitaltwins.dataplane.models import ErrorResponseException
from tqdm import tqdm

logger = get_logger(__name__)
MAX_MODELS_API_LIMIT = 250
# avagraw - Max number of models the API's dependency resolution can handle when models are created across multiple API calls.
MAX_MODELS_PER_BATCH = 30


def get_model_dependencies(model, model_id_to_model_map=None):
    """Return a list of dependency DTMIs for a given model"""
    dependencies = []

    # Add everything that would have dependency DTMIs, worry about flattening later
    if "contents" in model:
        components = [item["schema"] for item in model["contents"] if item["@type"] == "Component"]
        dependencies.extend(components)

    if "extends" in model:
        dependencies.append(model['extends'])

    # Go through gathered items, get the DTMI references, and flatten if needed
    no_dup = set()
    for item in dependencies:
        # Models defined in a DTDL can implement extensions of up to two interfaces.
        # These interfaces can be in the form of a DTMI reference, or a nested model.
        if isinstance(item, str):
            # If its just a string, thats a single DTMI reference, so just add that to our set
            no_dup.add(item)
            # Calculate recursive dependencies if model id to model map is passed
            if model_id_to_model_map is not None:
                dep_model = model_id_to_model_map[item]
                no_dup.update(set(get_model_dependencies(dep_model, model_id_to_model_map)))
        elif isinstance(item, dict):
            # If its a single nested model, get its dtmi reference, dependencies and add them
            no_dup.update(set(get_model_dependencies(item, model_id_to_model_map)))
        elif isinstance(item, list):
            # If its a list, could have DTMIs or nested models
            for sub_item in item:
                if isinstance(sub_item, str):
                    # If there are strings in the list, that's a DTMI reference, so add it
                    no_dup.add(sub_item)
                    # Calculate recursive dependencies if model id to model map is passed
                    if model_id_to_model_map is not None:
                        sub_dep_model = model_id_to_model_map[sub_item]
                        no_dup.update(set(get_model_dependencies(sub_dep_model, model_id_to_model_map)))
                elif isinstance(sub_item, dict):
                    # This is a nested model. Now go get its dependencies and add them
                    no_dup.update(set(get_model_dependencies(sub_item, model_id_to_model_map)))

    return list(no_dup)


class ModelProvider(DigitalTwinsProvider):
    def __init__(self, cmd, name, rg=None):
        super(ModelProvider, self).__init__(
            cmd=cmd, name=name, rg=rg,
        )
        self.model_sdk = self.get_sdk().digital_twin_models

    def add(self,
            models=None,
            from_directory=None,
            failure_policy=ADTModelCreateFailurePolicy.ROLLBACK.value,
            max_models_per_batch=None):
        if not any([models, from_directory]):
            raise RequiredArgumentMissingError("Provide either --models or --from-directory.")

        # If both arguments are provided. --models wins.
        payload = []
        models_per_batch = int(max_models_per_batch or MAX_MODELS_PER_BATCH)
        if models:
            models_result = process_json_arg(content=models, argument_name="models")

            if isinstance(models_result, list):
                payload.extend(models_result)
            elif isinstance(models_result, dict):
                payload.append(models_result)

        elif from_directory:
            payload = self._process_directory(from_directory=from_directory)

        logger.info("Models payload %s", json.dumps(payload))

        models_created = []
        try:
            # Process models in batches if models to process exceed the API limit
            if len(payload) > MAX_MODELS_API_LIMIT:

                model_id_to_model_map = {}
                for model_def in payload:
                    model_id_to_model_map[model_def['@id']] = model_def

                # Create a dictionary to categorize models by their number of dependencies
                dep_count_to_models_map = {}
                for model in payload:
                    num_dependencies = len(get_model_dependencies(model, model_id_to_model_map))
                    if num_dependencies not in dep_count_to_models_map:
                        dep_count_to_models_map[num_dependencies] = []
                    dep_count_to_models_map[num_dependencies].append(model)

                # Sort by dependency count
                dep_count_to_models_tuples = sorted(dep_count_to_models_map.items())
                models_batch = []
                response = []
                pbar = tqdm(total=len(payload), desc='Creating models...', ascii=' #')
                # The tuples being iterated are sorted by dependency count, hence models with 0 dependencies go first,
                # followed by models with 1 dependency, then 2 dependencies and so on... This ensures that all dependencies
                # of each model being added were either already added in a previous iteration or are in the current payload.
                for _, models_list in dep_count_to_models_tuples:
                    while len(models_batch) + len(models_list) > models_per_batch:
                        num_models_to_add = models_per_batch - len(models_batch)
                        models_batch.extend(models_list[0:num_models_to_add])
                        response.extend(self.model_sdk.add(models_batch, raw=True).response.json())
                        models_created.extend([model['@id'] for model in models_batch])
                        pbar.update(len(models_batch))
                        # Remove the model ids which have been processed
                        models_list = models_list[num_models_to_add:]
                        models_batch = []
                    models_batch.extend(models_list)
                # Process the last set of model ids
                if len(models_batch) > 0:
                    pbar.update(len(models_batch))
                    response.extend(self.model_sdk.add(models_batch, raw=True).response.json())
                pbar.close()
                return response
            return self.model_sdk.add(payload, raw=True).response.json()
        except ErrorResponseException as e:
            if len(models_created) > 0:
                pbar.close()
                # Delete all models created by this operation when the failure policy is set to 'Rollback'
                if failure_policy == ADTModelCreateFailurePolicy.ROLLBACK.value:
                    logger.error(
                        "Error creating models. Deleting {} models created by this operation...".format(len(models_created))
                    )
                    # Models will be deleted in the reverse order they were created.
                    # Hence, ensuring each model's dependencies are deleted after deleting the model.
                    models_created.reverse()
                    for model_id in models_created:
                        self.delete(model_id)
                # Models created by this operation are not deleted when the failure policy is set to 'None'
                elif failure_policy == ADTModelCreateFailurePolicy.NONE.value:
                    logger.error(
                        "Error creating current model batch. Successfully created {} models.".format(len(models_created))
                    )
                else:
                    raise InvalidArgumentValueError(
                        "Invalid failure policy: {}. Supported values are: '{}' and '{}'".format(
                            failure_policy, ADTModelCreateFailurePolicy.ROLLBACK.value, ADTModelCreateFailurePolicy.NONE.value
                        )
                    )
            # @vilit - hack to customize 403's to have more specific error messages
            if e.response.status_code == 403:
                error_text = "Current principal access is forbidden. Please validate rbac role assignments."
                raise ForbiddenError(error_text)
            handle_service_exception(e)

    def _process_directory(self, from_directory):
        logger.debug(
            "Documents contained in directory: {}, processing...".format(from_directory)
        )
        payload = []
        for entry in scantree(from_directory):
            if all(
                [not entry.name.endswith(".json"), not entry.name.endswith(".dtdl")]
            ):
                logger.debug(
                    "Skipping {} - model file must end with .json or .dtdl".format(
                        entry.path
                    )
                )
                continue
            entry_json = process_json_arg(content=entry.path, argument_name=entry.name)
            payload.append(entry_json)

        return payload

    def get(self, id, get_definition=False):
        try:
            return self.model_sdk.get_by_id(
                id=id, include_model_definition=get_definition, raw=True
            ).response.json()
        except ErrorResponseException as e:
            handle_service_exception(e)

    def list(
        self, get_definition=False, dependencies_for=None, top=None
    ):  # top is guarded for int() in arg def
        from azext_iot.sdk.digitaltwins.dataplane.models import DigitalTwinModelsListOptions

        list_options = DigitalTwinModelsListOptions(max_items_per_page=top)

        return self.model_sdk.list(
            dependencies_for=dependencies_for,
            include_model_definition=get_definition,
            digital_twin_models_list_options=list_options,
        )

    def update(self, id, decommission: bool):
        patched_model = [
            {"op": "replace", "path": "/decommissioned", "value": decommission}
        ]

        # Does not return model object upon updating
        try:
            self.model_sdk.update(id=id, update_model=patched_model)
        except ErrorResponseException as e:
            handle_service_exception(e)

        return self.get(id=id)

    def delete(self, id: str):
        try:
            self.model_sdk.delete(id=id)
        except ErrorResponseException as e:
            handle_service_exception(e)

    def delete_all(self):
        # Get all models
        incoming_pager = self.list(get_definition=True)
        incoming_result = []
        try:
            while True:
                incoming_result.extend(incoming_pager.advance_page())
        except StopIteration:
            pass
        except ErrorResponseException as e:
            handle_service_exception(e)

        # Build dict of model_id : set of parent_ids
        parsed_models = {model.id: set() for model in incoming_result}
        for model in incoming_result:
            # Parse dependents, add current model as parent of dependents
            dependencies = get_model_dependencies(model.model)
            for d_id in dependencies:
                parsed_models[d_id].add(model.id)

        def delete_parents(model_id, model_dict):
            # Check if current model has been deleted already
            if model_id not in model_dict:
                return

            # Delete parents first
            for parent_id in model_dict[model_id]:
                if parent_id in model_dict:
                    delete_parents(parent_id, model_dict)

            # Delete current model and remove references
            del model_dict[model_id]
            try:
                self.delete(model_id)
            except Exception as e:
                logger.warning(f"Could not delete model {model_id}; error is {e}")

        while len(parsed_models) > 0:
            model_id = next(iter(parsed_models))
            delete_parents(model_id, parsed_models)
