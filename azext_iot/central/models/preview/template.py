# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.util import CLIError

from azext_iot.central.models import BaseTemplate


class Template(BaseTemplate):
    def __init__(self, template: dict):
        super().__init__(template)
        try:
            self.id = template.get("id")
            self.solution_model = template.get("solutionModel")
            self.interfaces = self._extract_interfaces(template)
            self.schema_names = self._extract_schema_names(self.interfaces)
            self.components = self._extract_components(template)
            if self.components:
                self.component_schema_names = self._extract_schema_names(
                    self.components
                )

        except Exception:
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

            if dcm.get("implements"):
                interfaces.extend(dcm.get("implements"))

            return {
                self._get_interface_id(interface): self._extract_schemas(interface)
                for interface in interfaces
            }
        except Exception:
            details = "Unable to extract device schema from template '{}'.".format(
                self.id
            )
            raise CLIError(details)

    def _get_interface_id(self, interface) -> list:
        return (
            interface["schema"]["@id"] if interface.get("@type") else interface["@id"]
        )
