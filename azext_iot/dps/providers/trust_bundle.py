# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger
from azext_iot.dps.providers.discovery import DPSDiscovery
from azext_iot.common.shared import SdkType
from azext_iot._factory import SdkResolver
from azext_iot.common.utility import process_json_arg, handle_service_exception
from azext_iot.operations.generic import _execute_query
from azure.cli.core.azclierror import InvalidArgumentValueError
from azext_iot.sdk.dps.service.models import (
    ProvisioningServiceErrorDetailsException,
    X509CertificateWithMetadata,
)

logger = get_logger(__name__)


class TrustBundleProvider():
    def __init__(
        self,
        cmd,
        dps_name: str = None,
        resource_group_name: str = None,
        login: str = None,
        auth_type_dataplane: str = None,
    ):
        discovery = DPSDiscovery(cmd)
        target = discovery.get_target(dps_name, resource_group_name, login=login, auth_type=auth_type_dataplane)
        resolver = SdkResolver(target=target)
        self.sdk = resolver.get_sdk(SdkType.dps_sdk)
    
    def _create_certs(certificates: str):
        certificates_result = process_json_arg(content=certificates, argument_name="certificates" )
        trust_bundle_certs = []
        if isinstance(certificates_result, list):
            for cert in certificates_result:
                trust_bundle_certs.append(
                    X509CertificateWithMetadata(certificate=cert["certificate_definition"])
                )
        elif isinstance(certificates_result, dict):
            trust_bundle_certs.append(
                X509CertificateWithMetadata(certificate=certificates_result["certificate_definition"])
            )
        return trust_bundle_certs

    def get(self, trust_bundle_id: str):
        try:
            return self.sdk.trust_bundle.get(trust_bundle_id)
        except ProvisioningServiceErrorDetailsException as e:
            handle_service_exception(e)

    def list(self, with_certificate_data: bool, top: int = None):
        from azext_iot.sdk.dps.service.models import QuerySpecification
        try:
            query_command = "SELECT *"
            return self.sdk.trust_bundle.query(query_command, with_certificate_data=with_certificate_data)
            # query = [QuerySpecification(query=query_command)]
            # return _execute_query(query, self.sdk.trust_bundle.query, top)
        except ProvisioningServiceErrorDetailsException as e:
            handle_service_exception(e)
    
    def create(self, trust_bundle_id: str, certificates: str):
        try:
            dps_trust_bundles = self.list()
            dps_trust_bundle_ids = [bundle["id"] for bundle in dps_trust_bundles]
            if trust_bundle_id in dps_trust_bundle_ids:
                raise InvalidArgumentValueError(
                    "Trust bundle cannot be created. A trust bundle with id: {} already exists.".format(trust_bundle_id)
                )
            trust_bundle_certs = self._create_certs(certificates)
            return self.sdk.trust_bundle.create_or_update(trust_bundle_id, trust_bundle_certs)
        except ProvisioningServiceErrorDetailsException as e:
            handle_service_exception(e)
    
    def update(self, trust_bundle_id: str, certificates: str):
        try:
            dps_trust_bundles = self.list()
            dps_trust_bundle_ids = [bundle["id"] for bundle in dps_trust_bundles]
            if trust_bundle_id not in dps_trust_bundle_ids:
                raise InvalidArgumentValueError(
                    "Trust bundle cannot be updated. A trust bundle with id: {} does not exists.".format(trust_bundle_id)
                )
            trust_bundle_certs = self._create_certs(certificates)
            return self.sdk.trust_bundle.create_or_update(trust_bundle_id, trust_bundle_certs)
        except ProvisioningServiceErrorDetailsException as e:
            handle_service_exception(e)

    def delete(self, trust_bundle_id: str):
        try:
            return self.sdk.trust_bundle.delete(trust_bundle_id, if_match=None)
        except ProvisioningServiceErrorDetailsException as e:
            handle_service_exception(e)
    