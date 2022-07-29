# coding=utf-8
# --------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# Code generated by Microsoft (R) AutoRest Code Generator.
# Changes may cause incorrect behavior and will be lost if the code is regenerated.
# --------------------------------------------------------------------------

from ._models import ArmIdentity
from ._models import ArmUserIdentity
from ._models import CertificateBodyDescription
from ._models import CertificateDescription
from ._models import CertificateListDescription
from ._models import CertificateProperties
from ._models import CertificatePropertiesWithNonce
from ._models import CertificateVerificationDescription
from ._models import CertificateWithNonceDescription
from ._models import CloudToDeviceProperties
from ._models import EncryptionPropertiesDescription
from ._models import EndpointHealthData
from ._models import EnrichmentProperties
from ._models import ErrorDetails
from ._models import EventHubConsumerGroupBodyDescription
from ._models import EventHubConsumerGroupInfo
from ._models import EventHubConsumerGroupName
from ._models import EventHubProperties
from ._models import ExportDevicesRequest
from ._models import FailoverInput
from ._models import FallbackRouteProperties
from ._models import FeedbackProperties
from ._models import GroupIdInformation
from ._models import GroupIdInformationProperties
from ._models import ImportDevicesRequest
from ._models import IotHubCapacity
from ._models import IotHubDescription
from ._models import IotHubLocationDescription
from ._models import IotHubNameAvailabilityInfo
from ._models import IotHubProperties
from ._models import IotHubPropertiesDeviceStreams
from ._models import IotHubQuotaMetricInfo
from ._models import IotHubSkuDescription
from ._models import IotHubSkuInfo
from ._models import IpFilterRule
from ._models import JobResponse
from ._models import KeyVaultKeyProperties
from ._models import ManagedIdentity
from ._models import MatchedRoute
from ._models import MessagingEndpointProperties
from ._models import Name
from ._models import NetworkRuleSetIpRule
from ._models import NetworkRuleSetProperties
from ._models import Operation
from ._models import OperationDisplay
from ._models import OperationInputs
from ._models import PrivateEndpoint
from ._models import PrivateEndpointConnection
from ._models import PrivateEndpointConnectionProperties
from ._models import PrivateLinkResources
from ._models import PrivateLinkServiceConnectionState
from ._models import RegistryStatistics
from ._models import Resource
from ._models import RootCertificateProperties
from ._models import RouteCompilationError
from ._models import RouteErrorPosition
from ._models import RouteErrorRange
from ._models import RouteProperties
from ._models import RoutingCosmosDBSqlApiProperties
from ._models import RoutingEndpoints
from ._models import RoutingEventHubProperties
from ._models import RoutingMessage
from ._models import RoutingProperties
from ._models import RoutingServiceBusQueueEndpointProperties
from ._models import RoutingServiceBusTopicEndpointProperties
from ._models import RoutingStorageContainerProperties
from ._models import RoutingTwin
from ._models import RoutingTwinProperties
from ._models import SharedAccessSignatureAuthorizationRule
from ._models import StorageEndpointProperties
from ._models import SystemData
from ._models import TagsResource
from ._models import TestAllRoutesInput
from ._models import TestAllRoutesResult
from ._models import TestRouteInput
from ._models import TestRouteResult
from ._models import TestRouteResultDetails
from ._models import UserSubscriptionQuota
from ._models import UserSubscriptionQuotaListResult

from ._enums import AccessRights
from ._enums import AuthenticationType
from ._enums import Capabilities
from ._enums import CreatedByType
from ._enums import DefaultAction
from ._enums import EndpointHealthStatus
from ._enums import IotHubNameUnavailabilityReason
from ._enums import IotHubReplicaRoleType
from ._enums import IotHubScaleType
from ._enums import IotHubSku
from ._enums import IotHubSkuTier
from ._enums import IpFilterActionType
from ._enums import JobStatus
from ._enums import JobType
from ._enums import NetworkRuleIPAction
from ._enums import PrivateLinkServiceConnectionStatus
from ._enums import PublicNetworkAccess
from ._enums import ResourceIdentityType
from ._enums import RouteErrorSeverity
from ._enums import RoutingSource
from ._enums import RoutingStorageContainerPropertiesEncoding
from ._enums import TestResultStatus
from ._patch import __all__ as _patch_all
from ._patch import *  # type: ignore # pylint: disable=unused-wildcard-import
from ._patch import patch_sdk as _patch_sdk

__all__ = [
    "ArmIdentity",
    "ArmUserIdentity",
    "CertificateBodyDescription",
    "CertificateDescription",
    "CertificateListDescription",
    "CertificateProperties",
    "CertificatePropertiesWithNonce",
    "CertificateVerificationDescription",
    "CertificateWithNonceDescription",
    "CloudToDeviceProperties",
    "EncryptionPropertiesDescription",
    "EndpointHealthData",
    "EnrichmentProperties",
    "ErrorDetails",
    "EventHubConsumerGroupBodyDescription",
    "EventHubConsumerGroupInfo",
    "EventHubConsumerGroupName",
    "EventHubProperties",
    "ExportDevicesRequest",
    "FailoverInput",
    "FallbackRouteProperties",
    "FeedbackProperties",
    "GroupIdInformation",
    "GroupIdInformationProperties",
    "ImportDevicesRequest",
    "IotHubCapacity",
    "IotHubDescription",
    "IotHubLocationDescription",
    "IotHubNameAvailabilityInfo",
    "IotHubProperties",
    "IotHubPropertiesDeviceStreams",
    "IotHubQuotaMetricInfo",
    "IotHubSkuDescription",
    "IotHubSkuInfo",
    "IpFilterRule",
    "JobResponse",
    "KeyVaultKeyProperties",
    "ManagedIdentity",
    "MatchedRoute",
    "MessagingEndpointProperties",
    "Name",
    "NetworkRuleSetIpRule",
    "NetworkRuleSetProperties",
    "Operation",
    "OperationDisplay",
    "OperationInputs",
    "PrivateEndpoint",
    "PrivateEndpointConnection",
    "PrivateEndpointConnectionProperties",
    "PrivateLinkResources",
    "PrivateLinkServiceConnectionState",
    "RegistryStatistics",
    "Resource",
    "RootCertificateProperties",
    "RouteCompilationError",
    "RouteErrorPosition",
    "RouteErrorRange",
    "RouteProperties",
    "RoutingCosmosDBSqlApiProperties",
    "RoutingEndpoints",
    "RoutingEventHubProperties",
    "RoutingMessage",
    "RoutingProperties",
    "RoutingServiceBusQueueEndpointProperties",
    "RoutingServiceBusTopicEndpointProperties",
    "RoutingStorageContainerProperties",
    "RoutingTwin",
    "RoutingTwinProperties",
    "SharedAccessSignatureAuthorizationRule",
    "StorageEndpointProperties",
    "SystemData",
    "TagsResource",
    "TestAllRoutesInput",
    "TestAllRoutesResult",
    "TestRouteInput",
    "TestRouteResult",
    "TestRouteResultDetails",
    "UserSubscriptionQuota",
    "UserSubscriptionQuotaListResult",
    "AccessRights",
    "AuthenticationType",
    "Capabilities",
    "CreatedByType",
    "DefaultAction",
    "EndpointHealthStatus",
    "IotHubNameUnavailabilityReason",
    "IotHubReplicaRoleType",
    "IotHubScaleType",
    "IotHubSku",
    "IotHubSkuTier",
    "IpFilterActionType",
    "JobStatus",
    "JobType",
    "NetworkRuleIPAction",
    "PrivateLinkServiceConnectionStatus",
    "PublicNetworkAccess",
    "ResourceIdentityType",
    "RouteErrorSeverity",
    "RoutingSource",
    "RoutingStorageContainerPropertiesEncoding",
    "TestResultStatus",
]
__all__.extend([p for p in _patch_all if p not in __all__])
_patch_sdk()