# coding=utf-8
# --------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
#
# Code generated by Microsoft (R) AutoRest Code Generator.
# Changes may cause incorrect behavior and will be lost if the code is
# regenerated.
# --------------------------------------------------------------------------

from msrest.serialization import Model


class EnrollmentGroup(Model):
    """Enrollment group record.

    Variables are only populated by the server, and will be ignored when
    sending a request.

    All required parameters must be populated in order to send to Azure.

    :param enrollment_group_id: Required. Enrollment Group ID.
    :type enrollment_group_id: str
    :param attestation: Required. Attestation method used by the device.
    :type attestation: ~service.models.AttestationMechanism
    :param capabilities: Capabilities of the device.
    :type capabilities: ~service.models.DeviceCapabilities
    :param iot_hub_host_name: The Iot Hub host name.
    :type iot_hub_host_name: str
    :param initial_twin: Initial device twin.
    :type initial_twin: ~service.models.InitialTwin
    :param etag: The entity tag associated with the resource.
    :type etag: str
    :param provisioning_status: The provisioning status. Possible values
     include: 'enabled', 'disabled'. Default value: "enabled" .
    :type provisioning_status: str or ~service.models.enum
    :param reprovision_policy: The behavior when a device is re-provisioned to
     an IoT hub.
    :type reprovision_policy: ~service.models.ReprovisionPolicy
    :ivar created_date_time_utc: The DateTime this resource was created.
    :vartype created_date_time_utc: datetime
    :ivar last_updated_date_time_utc: The DateTime this resource was last
     updated.
    :vartype last_updated_date_time_utc: datetime
    :param allocation_policy: The allocation policy of this resource. This
     policy overrides the tenant level allocation policy for this individual
     enrollment or enrollment group. Possible values include 'hashed': Linked
     IoT hubs are equally likely to have devices provisioned to them,
     'geoLatency':  Devices are provisioned to an IoT hub with the lowest
     latency to the device.If multiple linked IoT hubs would provide the same
     lowest latency, the provisioning service hashes devices across those hubs,
     'static' : Specification of the desired IoT hub in the enrollment list
     takes priority over the service-level allocation policy, 'custom': Devices
     are provisioned to an IoT hub based on your own custom logic. The
     provisioning service passes information about the device to the logic, and
     the logic returns the desired IoT hub as well as the desired initial
     configuration. We recommend using Azure Functions to host your logic.
     Possible values include: 'hashed', 'geoLatency', 'static', 'custom'
    :type allocation_policy: str or ~service.models.enum
    :param iot_hubs: The list of IoT Hub hostnames the device(s) in this
     resource can be allocated to. Must be a subset of tenant level list of IoT
     hubs.
    :type iot_hubs: list[str]
    :param custom_allocation_definition: This tells DPS which webhook to call
     when using custom allocation.
    :type custom_allocation_definition:
     ~service.models.CustomAllocationDefinition
    """

    _validation = {
        'enrollment_group_id': {'required': True},
        'attestation': {'required': True},
        'created_date_time_utc': {'readonly': True},
        'last_updated_date_time_utc': {'readonly': True},
    }

    _attribute_map = {
        'enrollment_group_id': {'key': 'enrollmentGroupId', 'type': 'str'},
        'attestation': {'key': 'attestation', 'type': 'AttestationMechanism'},
        'capabilities': {'key': 'capabilities', 'type': 'DeviceCapabilities'},
        'iot_hub_host_name': {'key': 'iotHubHostName', 'type': 'str'},
        'initial_twin': {'key': 'initialTwin', 'type': 'InitialTwin'},
        'etag': {'key': 'etag', 'type': 'str'},
        'provisioning_status': {'key': 'provisioningStatus', 'type': 'str'},
        'reprovision_policy': {'key': 'reprovisionPolicy', 'type': 'ReprovisionPolicy'},
        'created_date_time_utc': {'key': 'createdDateTimeUtc', 'type': 'iso-8601'},
        'last_updated_date_time_utc': {'key': 'lastUpdatedDateTimeUtc', 'type': 'iso-8601'},
        'allocation_policy': {'key': 'allocationPolicy', 'type': 'str'},
        'iot_hubs': {'key': 'iotHubs', 'type': '[str]'},
        'custom_allocation_definition': {'key': 'customAllocationDefinition', 'type': 'CustomAllocationDefinition'},
    }

    def __init__(self, **kwargs):
        super(EnrollmentGroup, self).__init__(**kwargs)
        self.enrollment_group_id = kwargs.get('enrollment_group_id', None)
        self.attestation = kwargs.get('attestation', None)
        self.capabilities = kwargs.get('capabilities', None)
        self.iot_hub_host_name = kwargs.get('iot_hub_host_name', None)
        self.initial_twin = kwargs.get('initial_twin', None)
        self.etag = kwargs.get('etag', None)
        self.provisioning_status = kwargs.get('provisioning_status', "enabled")
        self.reprovision_policy = kwargs.get('reprovision_policy', None)
        self.created_date_time_utc = None
        self.last_updated_date_time_utc = None
        self.allocation_policy = kwargs.get('allocation_policy', None)
        self.iot_hubs = kwargs.get('iot_hubs', None)
        self.custom_allocation_definition = kwargs.get('custom_allocation_definition', None)
