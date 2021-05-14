# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import List
from knack.util import CLIError


class TemplateV1:
    def __init__(self, template: dict):
        self.raw_template = template
        try:
            self.id = template.get("id")
            self.name = template.get("displayName")
            self.interfaces = self._extract_interfaces(template)
            self.schema_names = self._extract_schema_names(self.interfaces)
            self.components = self._extract_components(template)
            if self.components:
                self.component_schema_names = self._extract_schema_names(
                    self.components
                )

        except:
            raise CLIError("Could not parse iot central device template.")

    def get_schema(self, name, is_component=False, identifier="") -> dict:
        entities = self.components if is_component else self.interfaces
        if identifier:
            # identifier specified, do a pointed lookup
            entry = entities.get(identifier, {})
            return entry.get(name)

        # find first matching name in any component
        for entry in entities.values():
            schema = entry.get(name)
            if schema:
                return schema

        # not found
        return None

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
                        component["name"]: self._extract_schemas(component)
                        for component in components
                    }
                return {}
            return {}
        except Exception:
            details = "Unable to extract schema for component from template '{}'.".format(
                self.id
            )
            raise CLIError(details)

    def _extract_root_interface_contents(self, dcm: dict) -> dict:
        rootContents = dcm.get("contents", {})
        contents = [
            entity for entity in rootContents if entity.get("@type") != "Component"
        ]

        return {"@id": dcm.get("@id", {}), "schema": {"contents": contents}}

    def _extract_interfaces(self, template: dict) -> dict:
        try:
            interfaces = []
            dcm = template.get("capabilityModel", {})

            if dcm.get("contents"):
                interfaces.append(self._extract_root_interface_contents(dcm))

            if dcm.get("extends"):
                interfaces.extend(dcm.get("extends"))

            return {
                interface["@id"]: self._extract_schemas(interface)
                for interface in interfaces
            }
        except Exception:
            details = "Unable to extract device schema from template '{}'.".format(
                self.id
            )
            raise CLIError(details)

    def _extract_schemas(self, entity: dict) -> dict:
        if entity.get("schema"):
            return {schema["name"]: schema for schema in entity["schema"]["contents"]}
        else:
            return {schema["name"]: schema for schema in entity["contents"]}

    def _extract_schema_names(self, entity: dict) -> dict:
        return {
            entity_name: list(entity_schemas.keys())
            for entity_name, entity_schemas in entity.items()
        }

    def _get_interface_list_property(self, property_name) -> List:
        # returns the list of interfaces where property with property_name is defined
        return [
            interface
            for interface, schema in self.schema_names.items()
            if property_name in schema
        ]
