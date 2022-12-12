# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from azure.cli.core.azclierror import CLIInternalError

from azext_iot.central.models import BaseTemplate


class Template(BaseTemplate):
    def __init__(self, template: dict):
        super().__init__(template)
        try:
            self.id = template.get("@id")
            self.deployment_manifest = template.get("deploymentManifest")
            self.interfaces = self._extract_interfaces(template)
            self.schema_names = self._extract_schema_names(self.interfaces)
            self.components = self._extract_components(template)
            if self.components:
                self.component_schema_names = self._extract_schema_names(
                    self.components
                )

            self.modules = self._extract_modules(template)

        except Exception:
            raise CLIInternalError("Could not parse iot central device template.")

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
            raise CLIInternalError(details)

    def _extract_modules(self, template: dict) -> dict:
        try:
            modules = []

            dcm = template.get("capabilityModel", {})
            contents = dcm.get("contents", {})

            for content in contents:
                # Module
                if 'EdgeModule' in content['@type'] and content.get("target"):
                    # For reusing some functions, add "capabilityModel" key here
                    template = {"capabilityModel": content.get("target")[0]}

                    id = content.get("@id")
                    interfaces = self._extract_interfaces(template)
                    schema_names = self._extract_schema_names(interfaces)
                    components = self._extract_components(template)
                    if components:
                        component_schema_names = self._extract_schema_names(components)

                    modules.append({
                        'id': id,
                        'interfaces': interfaces,
                        'schema_names': schema_names,
                        'components': components,
                        'component_schema_names': component_schema_names
                    })

            return modules

        except Exception:
            details = "Unable to extract device module schema from template '{}'.".format(
                self.id
            )
            raise CLIInternalError(details)

    def get_id_key(self):
        return "@id"

    def get_type_key(self):
        return "@type"
