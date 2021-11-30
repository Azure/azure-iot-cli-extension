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


class DeviceRegistrationState(Model):
    """Device registration state.

    Variables are only populated by the server, and will be ignored when
    sending a request.

    :ivar registration_id: This id is used to uniquely identify a device
     registration of an enrollment.
     A case-insensitive string (up to 128 characters long) of alphanumeric
     characters plus certain special characters : . _ -. No special characters
     allowed at start or end.
    :vartype registration_id: str
    :ivar created_date_time_utc: Registration create date time (in UTC).
    :vartype created_date_time_utc: datetime
    :ivar assigned_hub: Assigned Azure IoT Hub.
    :vartype assigned_hub: str
    :ivar device_id: Device ID.
    :vartype device_id: str
    :ivar status: Enrollment status. Possible values include: 'unassigned',
     'assigning', 'assigned', 'failed', 'disabled'
    :vartype status: str or ~service.models.enum
    :ivar substatus: Substatus for 'Assigned' devices. Possible values include
     - 'initialAssignment': Device has been assigned to an IoT hub for the
     first time, 'deviceDataMigrated': Device has been assigned to a different
     IoT hub and its device data was migrated from the previously assigned IoT
     hub. Device data was removed from the previously assigned IoT hub,
     'deviceDataReset':  Device has been assigned to a different IoT hub and
     its device data was populated from the initial state stored in the
     enrollment. Device data was removed from the previously assigned IoT hub,
     'reprovisionedToInitialAssignment': Device has been re-provisioned to a
     previously assigned IoT hub. Possible values include: 'initialAssignment',
     'deviceDataMigrated', 'deviceDataReset',
     'reprovisionedToInitialAssignment'
    :vartype substatus: str or ~service.models.enum
    :ivar error_code: Error code.
    :vartype error_code: int
    :ivar error_message: Error message.
    :vartype error_message: str
    :ivar last_updated_date_time_utc: Last updated date time (in UTC).
    :vartype last_updated_date_time_utc: datetime
    :ivar etag: The entity tag associated with the resource.
    :vartype etag: str
    :ivar payload: Custom allocation payload returned from the webhook to the
     device.
    :vartype payload: object
    """

    _validation = {
        'registration_id': {'readonly': True},
        'created_date_time_utc': {'readonly': True},
        'assigned_hub': {'readonly': True},
        'device_id': {'readonly': True},
        'status': {'readonly': True},
        'substatus': {'readonly': True},
        'error_code': {'readonly': True},
        'error_message': {'readonly': True},
        'last_updated_date_time_utc': {'readonly': True},
        'etag': {'readonly': True},
        'payload': {'readonly': True},
    }

    _attribute_map = {
        'registration_id': {'key': 'registrationId', 'type': 'str'},
        'created_date_time_utc': {'key': 'createdDateTimeUtc', 'type': 'iso-8601'},
        'assigned_hub': {'key': 'assignedHub', 'type': 'str'},
        'device_id': {'key': 'deviceId', 'type': 'str'},
        'status': {'key': 'status', 'type': 'str'},
        'substatus': {'key': 'substatus', 'type': 'str'},
        'error_code': {'key': 'errorCode', 'type': 'int'},
        'error_message': {'key': 'errorMessage', 'type': 'str'},
        'last_updated_date_time_utc': {'key': 'lastUpdatedDateTimeUtc', 'type': 'iso-8601'},
        'etag': {'key': 'etag', 'type': 'str'},
        'payload': {'key': 'payload', 'type': 'object'},
    }

    def __init__(self, **kwargs):
        super(DeviceRegistrationState, self).__init__(**kwargs)
        self.registration_id = None
        self.created_date_time_utc = None
        self.assigned_hub = None
        self.device_id = None
        self.status = None
        self.substatus = None
        self.error_code = None
        self.error_message = None
        self.last_updated_date_time_utc = None
        self.etag = None
        self.payload = None
