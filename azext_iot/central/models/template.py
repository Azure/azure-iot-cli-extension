# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.util import CLIError


class Template:
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
        if is_component:
            if identifier:
                # identifier specified, do a pointed lookup
                component = self.components.get(identifier, {})
                return component.get(name)

            # find first matching name in any component
            for component in self.components.values():
                schema = component.get(name)
                if schema:
                    return schema
        else:
            # identifier specified, do a pointed lookup
            if identifier:
                interface = self.interfaces.get(identifier, {})
                return interface.get(name)

            # find first matching name in any interface
            for interface in self.interfaces.values():
                schema = interface.get(name)
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

        except Exception:
            details = "Unable to extract schema for component from template '{}'.".format(
                self.id
            )
            raise CLIError(details)

    def _extract_root_interface_contents(self, dcm: dict):
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

            if dcm.get("@type") == "CapabilityModel":
                interfaces.extend(dcm.get("implements"))
            else:
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
        return {schema["name"]: schema for schema in entity["schema"]["contents"]}

    def _extract_schema_names(self, entity: dict) -> dict:
        return {
            entity_name: list(entity_schemas.keys())
            for entity_name, entity_schemas in entity.items()
        }

    def _get_interface_list_property(self, property_name):
        # returns the list of interfaces where property with property_name is defined
        return [
            interface
            for interface, schema in self.schema_names.items()
            if property_name in schema
        ]
