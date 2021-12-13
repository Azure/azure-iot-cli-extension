# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.util import CLIError


class BaseTemplate:
    def __init__(self, template: dict):
        self.id = None
        self.schema_names = None
        self.raw_template = template
        try:
            self.name = template.get("displayName")
            self.components = self._extract_components(template)
            if self.components:
                self.component_schema_names = self._extract_schema_names(
                    self.components
                )

        except Exception:
            raise CLIError("Could not parse iot central device template.")

    def _get_schema_name(self, schema) -> str:
        return "name" if "name" in schema else "@id"

    def _extract_schemas(self, entity: dict) -> dict:
        schema = entity.get("schema")
        if schema is not None:
            # if schema.get("contents"):
            return {
                content[self._get_schema_name(content)]: content
                for content in schema["contents"]
            }
            # else:
            #     return entity
        else:
            return {
                schema[self._get_schema_name(schema)]: schema
                for schema in entity["contents"]
            }

    def _extract_schema_names(self, entity: dict) -> dict:
        return {
            entity_name: list(entity_schemas.keys())
            for entity_name, entity_schemas in entity.items()
        }

    def _get_interface_list_property(self, property_name) -> list:
        # returns the list of interfaces where property with property_name is defined
        return [
            interface
            for interface, schema in self.schema_names.items()
            if property_name in schema
        ]

    def _extract_components(self, template: dict) -> dict:
        try:
            dcm = template.get("capabilityModel", {})
            if dcm.get("contents"):
                rootContents = dcm.get("contents", {})
                components = [
                    entity
                    for entity in rootContents
                    if entity.get("@type") == "Component"
                ]

                if components:
                    return {
                        component[
                            self._get_schema_name(component)
                        ]: self._extract_schemas(component)
                        for component in components
                    }
                return {}
            return {}
        except Exception:
            details = (
                "Unable to extract schema for component from template '{}'.".format(
                    self.id
                )
            )
            raise CLIError(details)
