# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from argcomplete.completers import FilesCompleter  # pylint: disable=import-error
from knack.arguments import CLIArgumentType
from azure.cli.core.commands.parameters import (get_location_type,
                                                file_type,
                                                get_resource_name_completion_list,
                                                get_enum_type,
                                                get_three_state_flag,
                                                tags_type)

from azure.cli.command_modules.iot.shared import (EndpointType,
                                                  RouteSourceType,
                                                  EncodingFormat,
                                                  RenewKeyType,
                                                  AuthenticationType)


from .custom import KeyType, SimpleAccessRights
from .shared import IotDpsSku, IotHubSku, AccessRightsDescription, IotHubAuthenticationType
from azure.cli.command_modules.iot._validators import (validate_policy_permissions,
                                                       validate_retention_days,
                                                       validate_fileupload_notification_max_delivery_count,
                                                       validate_fileupload_notification_ttl,
                                                       validate_fileupload_sas_ttl,
                                                       validate_feedback_ttl,
                                                       validate_feedback_lock_duration,
                                                       validate_fileupload_notification_lock_duration,
                                                       validate_feedback_max_delivery_count,
                                                       validate_c2d_max_delivery_count,
                                                       validate_c2d_ttl)


hub_name_type = CLIArgumentType(
    completer=get_resource_name_completion_list('Microsoft.Devices/IotHubs'),
    help='IoT Hub name.')

dps_name_type = CLIArgumentType(
    options_list=['--name', '-n'],
    completer=get_resource_name_completion_list('Microsoft.Devices/ProvisioningServices'),
    help='IoT Hub Device Provisioning Service name')

mi_system_assigned_type = CLIArgumentType(
    options_list=['--mi-system-assigned'],
    help='Provide this flag to use system assigned identity.')

system_assigned_type = CLIArgumentType(
    options_list=['--system-assigned'],
    help='Provide this flag to refer to the system-assigned identity.')


def load_arguments(self, _):  # pylint: disable=too-many-statements
    # Arguments for IoT DPS
    with self.argument_context('iot dps') as c:
        c.argument('tags', tags_type)

    # Direct DPS resource commands use --name -n
    for subgroup in ['create', 'update', 'show', 'delete']:
        with self.argument_context('iot dps {}'.format(subgroup)) as c:
            c.argument('dps_name', dps_name_type, id_part='name')

    with self.argument_context('iot dps create') as c:
        c.argument('location', get_location_type(self.cli_ctx),
                   help='Location of your IoT Hub Device Provisioning Service. '
                   'Default is the location of target resource group.')
        c.argument('sku', arg_type=get_enum_type(IotDpsSku),
                   help='Pricing tier for the IoT Hub Device Provisioning Service.')
        c.argument('unit', help='Units in your IoT Hub Device Provisioning Service.', type=int)
        c.argument('enable_data_residency', arg_type=get_three_state_flag(),
                   options_list=['--enforce-data-residency', '--edr'],
                   help='Enforce data residency for this IoT Hub Device Provisioning Service by disabling '
                   'cross geo-pair disaster recovery. This property is immutable once set on the resource. '
                   'Only available in select regions. Learn more at https://aka.ms/dpsdr')

    # plan to slowly align this with extension naming patterns - n should be aligned with dps_name
    for subgroup in ['linked-hub', 'certificate']:
        with self.argument_context('iot dps {}'.format(subgroup)) as c:
            c.argument('dps_name', options_list=['--dps-name'], id_part=None,
                       help='IoT Hub Device Provisioning Service name.', arg_group=None)

    # Identity uses --name like IoT Hub
    with self.argument_context('iot dps identity') as c:
        c.argument('dps_name', options_list=['--name', '-n'],
                   help='IoT Hub Device Provisioning Service name.', arg_group=None)

    # To replace above
    for subgroup in ['policy']:
        with self.argument_context('iot dps {}'.format(subgroup)) as c:
            c.argument('dps_name', options_list=['--dps-name', '-n'], id_part=None,
                       help='IoT Hub Device Provisioning Service name.', arg_group=None)

    with self.argument_context('iot dps policy') as c:
        c.argument('access_policy_name', options_list=['--policy-name', '--pn'],
                   help='A friendly name for DPS access policy.')

    for subgroup in ['create', 'update']:
        with self.argument_context('iot dps policy {}'.format(subgroup)) as c:
            c.argument('rights', options_list=['--rights', '-r'], nargs='+',
                       arg_type=get_enum_type(AccessRightsDescription),
                       help='Access rights for the IoT Hub Device Provisioning Service. '
                            'Use space-separated list for multiple rights.')

    with self.argument_context('iot dps policy create') as c:
        c.argument('primary_key', help='Primary SAS key value, if not provided it will be generated by the service')
        c.argument('secondary_key', help='Secondary SAS key value, if not provided it will be generated by the service')

    with self.argument_context('iot dps policy update') as c:
        c.argument('primary_key', help='Primary SAS key value. Set to empty string '
                   'in order to regenerate a new primary key.')
        c.argument('secondary_key', help='Secondary SAS key value. Set to empty string '
                   'in order to regenerate a new secondary key.')

    with self.argument_context('iot dps linked-hub') as c:
        c.argument('linked_hub', options_list=['--linked-hub'], help='Host name of linked IoT Hub.')

    with self.argument_context('iot dps linked-hub create') as c:
        c.argument('connection_string',
                   options_list=['--connection-string', '--cs'],
                   help='Connection string of the IoT hub. Required if hub name is not provided using --hub-name.',
                   arg_group='IoT Hub Identifier')
        c.argument('hub_name',
                   options_list=['--hub-name', '--hn'],
                   help='IoT Hub name.',
                   arg_group='IoT Hub Identifier')
        c.argument('hub_resource_group',
                   options_list=['--hub-resource-group', '--hrg'],
                   help='IoT Hub resource group name.',
                   arg_group='IoT Hub Identifier')
        c.argument('location', get_location_type(self.cli_ctx),
                   help='Location of the IoT hub.',
                   arg_group='IoT Hub Identifier',
                   deprecate_info=c.deprecate(hide=True))
        c.argument('authentication_type',
                   options_list=['--authentication-type', '--auth-type'],
                   arg_type=get_enum_type(IotHubAuthenticationType),
                   help='Authentication type for the linked IoT Hub. '
                   "'KeyBased' uses a connection string. "
                   "'SystemAssigned' uses the DPS system-assigned managed identity. "
                   "'UserAssigned' uses a user-assigned managed identity.")
        c.argument('user_assigned_identity',
                   options_list=['--user-assigned-identity', '--uai'],
                   help='User-assigned managed identity resource ID. '
                   'Required when authentication type is UserAssigned.')
        c.argument('hostname_type',
                   options_list=['--hostname-type', '--ht'],
                   arg_type=get_enum_type(["auto", "device", "classic"]),
                   default="auto",
                   help="Type of IoT Hub hostname to use when linking. "
                   "'auto' uses the TLS 1.3 device hostname if available, classic otherwise. "
                   "'device' uses the TLS 1.3 device hostname (errors if not GWv2). "
                   "'classic' uses the classic hostname (hub.azure-devices.net). "
                   "Only applies when --hub-name is provided.")
        c.argument('apply_allocation_policy',
                   help='A boolean indicating whether to apply allocation policy to the IoT hub.',
                   arg_type=get_three_state_flag())
        c.argument('allocation_weight', help='Allocation weight of the IoT hub.', type=int)

    with self.argument_context('iot dps linked-hub update') as c:
        c.argument('linked_hub',
                   options_list=['--linked-hub'],
                   help='Full host name of the linked IoT Hub (e.g. `myhub.device.azure-devices.net`). '
                   'Use this to disambiguate when --hub-name resolves to multiple entries.',
                   arg_group='Linked Hub Identifier')
        c.argument('hub_name',
                   options_list=['--hub-name', '--hn'],
                   help='IoT Hub short name. Preferred over --linked-hub; resolves to the correct '
                   'entry regardless of classic/device hostname.',
                   arg_group='Linked Hub Identifier')
        c.argument('authentication_type',
                   options_list=['--authentication-type', '--auth-type'],
                   arg_type=get_enum_type(IotHubAuthenticationType),
                   help='Switch the linked hub to a different authentication type. '
                   "'KeyBased' uses a connection string (supplied via --connection-string, "
                   "otherwise auto-fetched from the identified hub). "
                   "'SystemAssigned' uses the DPS system-assigned managed identity. "
                   "'UserAssigned' uses a user-assigned managed identity.")
        c.argument('user_assigned_identity',
                   options_list=['--user-assigned-identity', '--uai'],
                   help='User-assigned managed identity resource ID. '
                   'Required when --authentication-type is UserAssigned.')
        c.argument('connection_string',
                   options_list=['--connection-string', '--cs'],
                   help='IoT Hub connection string to use when switching to KeyBased authentication. '
                   'If omitted, the key is auto-fetched from the identified hub.')
        c.argument('apply_allocation_policy',
                   help='A boolean indicating whether to apply allocation policy to the IoT hub.',
                   arg_type=get_three_state_flag())
        c.argument('allocation_weight', help='Allocation weight of the IoT hub.', type=int)

    with self.argument_context('iot dps certificate') as c:
        c.argument('certificate_path', options_list=['--path', '-p'], type=file_type,
                   completer=FilesCompleter([".cer", ".pem"]),
                   help='The path to the file containing the certificate.',
                   arg_group=None)
        c.argument('certificate_name', options_list=['--certificate-name', '--name', '-n'],
                   help='A friendly name for the certificate.')
        c.argument('etag', options_list=['--etag', '-e'], help='Entity Tag (etag) of the object.')

    for subgroup in ['create', 'update']:
        with self.argument_context('iot dps certificate {}'.format(subgroup)) as c:
            c.argument('is_verified', options_list=['--verified', '-v'], arg_type=get_three_state_flag(),
                       help='A boolean indicating whether or not the certificate is verified.')

    # Arguments for IoT Hub
    with self.argument_context('iot hub') as c:
        c.argument('hub_name', hub_name_type, options_list=['--name', '-n'], id_part='name', arg_group=None)
        c.argument("etag", options_list=["--etag", "-e"],
                   help="Etag or entity tag corresponding to the last state of the resource."
                        " If no etag is provided the value '*' is used.")
        c.argument('sku', arg_type=get_enum_type(IotHubSku),
                   help='Pricing tier for Azure IoT Hub. '
                        'Note that only one free IoT hub instance (F1) is allowed in each '
                        'subscription. Exception will be thrown if free instances exceed one.')
        c.argument('unit', help='Units in your IoT Hub.', type=int, arg_group=None)
        c.argument('partition_count',
                   help='The number of partitions of the backing Event Hub for device-to-cloud messages.', type=int)
        c.argument('retention_day', options_list=['--retention-day', '--rd'],
                   type=int, validator=validate_retention_days,
                   help='Specifies how long this IoT hub will maintain device-to-cloud events, between 1 and 7 days.')
        c.argument('c2d_ttl', options_list=['--c2d-ttl', '--ct'],
                   type=int, validator=validate_c2d_ttl,
                   help='The amount of time a message is available for the device to consume before it is expired'
                        ' by IoT Hub, between 1 and 48 hours.')
        c.argument('c2d_max_delivery_count', options_list=['--c2d-max-delivery-count', '--cdd'],
                   type=int, validator=validate_c2d_max_delivery_count,
                   help='The number of times the IoT hub will attempt to deliver a cloud-to-device'
                        ' message to a device, between 1 and 100.')
        c.argument('disable_local_auth', options_list=['--disable-local-auth', '--dla'],
                   arg_type=get_three_state_flag(),
                   help='A boolean indicating whether or not to disable '
                        'IoT hub scoped SAS keys for authentication.')
        c.argument('disable_device_sas', options_list=['--disable-device-sas', '--dds'],
                   arg_type=get_three_state_flag(),
                   help='A boolean indicating whether or not to disable all device '
                        '(including Edge devices but excluding modules) scoped SAS keys for authentication')
        c.argument('disable_module_sas', options_list=['--disable-module-sas', '--dms'],
                   arg_type=get_three_state_flag(),
                   help='A boolean indicating whether or not to disable module-scoped SAS keys for authentication.')
        c.argument('feedback_ttl', options_list=['--feedback-ttl', '--ft'],
                   type=int, validator=validate_feedback_ttl,
                   help='The period of time for which the IoT hub will maintain the feedback for expiration'
                        ' or delivery of cloud-to-device messages, between 1 and 48 hours.')
        c.argument('feedback_lock_duration', options_list=['--feedback-lock-duration', '--fld'],
                   type=int, validator=validate_feedback_lock_duration,
                   help='The lock duration for the feedback queue, between 5 and 300 seconds.')
        c.argument('feedback_max_delivery_count', options_list=['--feedback-max-delivery-count', '--fd'],
                   type=int, validator=validate_feedback_max_delivery_count,
                   help='The number of times the IoT hub attempts to'
                        ' deliver a message on the feedback queue, between 1 and 100.')
        c.argument('enable_fileupload_notifications', options_list=['--fileupload-notifications', '--fn'],
                   arg_type=get_three_state_flag(),
                   help='A boolean indicating whether to log information about uploaded files to the'
                        ' messages/servicebound/filenotifications IoT Hub endpoint.')
        c.argument('fileupload_notification_lock_duration',
                   options_list=['--fileupload-notification-lock-duration', '--fnld'],
                   type=int, validator=validate_fileupload_notification_lock_duration,
                   help='The lock duration for the file upload notifications queue, between 5 and 300 seconds.')
        c.argument('fileupload_notification_max_delivery_count', type=int,
                   options_list=['--fileupload-notification-max-delivery-count', '--fnd'],
                   validator=validate_fileupload_notification_max_delivery_count,
                   help='The number of times the IoT hub will attempt to deliver a file notification message,'
                        ' between 1 and 100.')
        c.argument('fileupload_notification_ttl', options_list=['--fileupload-notification-ttl', '--fnt'],
                   type=int, validator=validate_fileupload_notification_ttl,
                   help='The amount of time a file upload notification is available for the service to'
                        ' consume before it is expired by IoT Hub, between 1 and 48 hours.')
        c.argument('fileupload_storage_connectionstring',
                   options_list=['--fileupload-storage-connectionstring', '--fcs'],
                   help='The connection string for the Azure Storage account to which files are uploaded.')
        c.argument('fileupload_storage_authentication_type',
                   arg_type=get_enum_type(AuthenticationType),
                   options_list=['--fileupload-storage-auth-type', '--fsa'],
                   help='The authentication type for the Azure Storage account to which files are uploaded.')
        c.argument('fileupload_storage_container_uri',
                   options_list=['--fileupload-storage-container-uri', '--fcu'],
                   help='The container URI for the Azure Storage account to which files are uploaded.',
                   deprecate_info=c.deprecate(hide=True))
        c.argument('fileupload_storage_container_name',
                   options_list=['--fileupload-storage-container-name', '--fc'],
                   help='The name of the root container where you upload files. The container need not exist but'
                        ' should be creatable using the connectionString specified.')
        c.argument('fileupload_sas_ttl', options_list=['--fileupload-sas-ttl', '--fst'],
                   type=int, validator=validate_fileupload_sas_ttl,
                   help='The amount of time a SAS URI generated by IoT Hub is valid before it expires,'
                        ' between 1 and 24 hours.')
        c.argument('fileupload_storage_identity',
                   options_list=['--fileupload-storage-identity', '--fsi'],
                   help="The managed identity to use for file upload authentication. Use '[system]' to "
                        "refer to the system-assigned managed identity or a resource ID to refer to a "
                        "user-assigned managed identity.")
        c.argument('min_tls_version', options_list=['--min-tls-version', '--mintls'],
                   type=str, help='Specify the minimum TLS version to support for this hub. Can be set to '
                                  '"1.0" or "1.2". For example, minimum TLS version set to "1.2" '
                                  'results in clients that use a TLS version below 1.2 to be rejected.')
        c.argument('system_identity', options_list=['--mi-system-assigned'],
                   arg_type=get_three_state_flag(),
                   help="Enable system-assigned managed identity for this hub")
        c.argument('user_identities', options_list=['--mi-user-assigned'],
                   nargs='*', help="Enable user-assigned managed identities for this hub. "
                   "Accept space-separated list of identity resource IDs.")
        c.argument('identity_role', options_list=['--role'],
                   help="Role to assign to the hub's system-assigned managed identity.")
        c.argument('identity_scopes', options_list=['--scopes'], nargs='*',
                   help="Space separated list of scopes to assign the role (--role) "
                   "for the system-assigned managed identity.")

    # Tag-type should only be for hub create/update (conflicts with device-twin update twin tags)
    for cmd in ["iot hub create", "iot hub update"]:
        with self.argument_context(cmd) as c:
            c.argument('tags', tags_type, arg_group=None)

    with self.argument_context('iot hub identity assign') as c:
        c.argument('system_identity', options_list=['--system-assigned', '--system'],
                   arg_type=get_three_state_flag(),
                   nargs='*', help="Assign a system-assigned managed identity to this hub.")
        c.argument('user_identities', options_list=['--user-assigned', '--user'],
                   nargs='+', help="Assign user-assigned managed identities to this hub. "
                   "Accept space-separated list of identity resource IDs.")

    with self.argument_context('iot hub identity remove') as c:
        c.argument('system_identity', options_list=['--system-assigned', '--system'],
                   arg_type=get_three_state_flag(),
                   nargs='*', help="Remove a system-assigned managed identity from this hub.")
        c.argument('user_identities', options_list=['--user-assigned', '--user'],
                   nargs='*', help="Remove user-assigned managed identities from this hub. "
                   "Accept space-separated list of identity resource IDs.")

    for subgroup in ['consumer-group', 'policy', 'certificate', 'routing-endpoint', 'route']:
        with self.argument_context('iot hub {}'.format(subgroup)) as c:
            c.argument('hub_name', options_list=['--hub-name'])

    with self.argument_context('iot hub route') as c:
        c.argument('route_name', options_list=['--route-name', '--name', '-n'], help='Name of the Route.')
        c.argument('endpoint_name', options_list=['--endpoint-name', '--endpoint', '--en'],
                   help='Name of the routing endpoint.')
        c.argument('condition', options_list=['--condition', '-c'],
                   help='Condition that is evaluated to apply the routing rule.')
        c.argument('enabled', options_list=['--enabled', '-e'], arg_type=get_three_state_flag(),
                   help='A boolean indicating whether to enable route to the Iot hub.')
        c.argument('source_type', arg_type=get_enum_type(RouteSourceType),
                   options_list=['--source-type', '--type', '--source', '-s'], help='Source of the route.')

    with self.argument_context('iot hub route test') as c:
        c.argument('body', options_list=['--body', '-b'], help='Body of the route message.')
        c.argument('app_properties', options_list=['--app-properties', '--ap'],
                   help='App properties of the route message.')
        c.argument('system_properties', options_list=['--system-properties', '--sp'],
                   help='System properties of the route message.')

    with self.argument_context('iot hub routing-endpoint') as c:
        c.argument('endpoint_name', options_list=['--endpoint-name', '--name', '-n'],
                   help='Name of the Routing Endpoint.')
        c.argument('endpoint_resource_group', options_list=['--endpoint-resource-group', '--erg', '-r'],
                   help='Resource group of the Endpoint resoure.')
        c.argument('endpoint_subscription_id', options_list=['--endpoint-subscription-id', '-s'],
                   help='SubscriptionId of the Endpoint resource.')
        c.argument('connection_string', options_list=['--connection-string', '-c'],
                   help='Connection string of the Routing Endpoint.')
        c.argument('container_name', options_list=['--container-name', '--container'],
                   help='Name of the storage container.')
        c.argument('endpoint_type', arg_type=get_enum_type(EndpointType),
                   options_list=['--endpoint-type', '--type', '-t'], help='Type of the Routing Endpoint.')
        c.argument('encoding', options_list=['--encoding'], arg_type=get_enum_type(EncodingFormat),
                   help='Encoding format for the container. The default is AVRO. '
                        'Note that this field is applicable only for blob container endpoints.')
        c.argument('endpoint_uri', options_list=['--endpoint-uri'],
                   help='The uri of the endpoint resource.')
        c.argument('entity_path', options_list=['--entity-path'],
                   help='The entity path of the endpoint resource.')

    with self.argument_context('iot hub routing-endpoint create') as c:
        c.argument('batch_frequency', options_list=['--batch-frequency', '-b'], type=int,
                   help='Request batch frequency in seconds. The maximum amount of time that can elapse before data is'
                        ' written to a blob, between 60 and 720 seconds.')
        c.argument('chunk_size_window', options_list=['--chunk-size', '-w'], type=int,
                   help='Request chunk size in megabytes(MB). The maximum size of blobs, between 10 and 500 MB.')
        c.argument('file_name_format', options_list=['--file-name-format', '--ff'],
                   help='File name format for the blob. The file name format must contain {iothub},'
                        ' {partition}, {YYYY}, {MM}, {DD}, {HH} and {mm} fields. All parameters are'
                        ' mandatory but can be reordered with or without delimiters.')
        c.argument('authentication_type', options_list=['--auth-type'], arg_type=get_enum_type(AuthenticationType),
                   help='Authentication type for the endpoint. The default is keyBased.')
        c.argument('identity', help='Use a system-assigned or user-assigned managed identity for endpoint '
                   'authentication. Use "[system]" to refer to the system-assigned identity or a resource ID '
                   'to refer to a user-assigned identity. If you use --auth-type without this parameter, '
                   'system-assigned managed identity is assumed.')

    with self.argument_context('iot hub certificate') as c:
        c.argument('certificate_path', options_list=['--path', '-p'], type=file_type,
                   completer=FilesCompleter([".cer", ".pem"]), help='The path to the file containing the certificate.')
        c.argument('certificate_name', options_list=['--name', '-n'], help='A friendly name for the certificate.')

    for subgroup in ['create', 'update']:
        with self.argument_context('iot hub certificate {}'.format(subgroup)) as c:
            c.argument('is_verified', options_list=['--verified', '-v'], arg_type=get_three_state_flag(),
                       help='A boolean indicating whether or not the certificate is verified.')

    with self.argument_context('iot hub consumer-group') as c:
        c.argument('consumer_group_name', options_list=['--name', '-n'], id_part='child_name_2',
                   help='Event hub consumer group name.')
        c.argument('event_hub_name', id_part='child_name_1', help='Event hub endpoint name.')

    with self.argument_context('iot hub policy') as c:
        c.argument('policy_name', options_list=['--name', '-n'], id_part='child_name_1',
                   help='Shared access policy name.')
        permission_values = ', '.join([x.value for x in SimpleAccessRights])
        c.argument('permissions', nargs='*', validator=validate_policy_permissions, type=str.lower,
                   help='Permissions of shared access policy. Use space-separated list for multiple permissions. '
                        'Possible values: {}'.format(permission_values))

    with self.argument_context('iot hub policy renew-key') as c:
        c.argument('regenerate_key', options_list=['--renew-key', '--rk'], arg_type=get_enum_type(RenewKeyType),
                   help='Regenerate keys')

    with self.argument_context('iot hub create') as c:
        c.argument('hub_name', completer=None)
        c.argument('location', get_location_type(self.cli_ctx),
                   help='Location of your IoT Hub. Default is the location of target resource group.')
        c.argument('enable_data_residency', arg_type=get_three_state_flag(),
                   options_list=['--enforce-data-residency', '--edr'],
                   help='Enforce data residency for this IoT Hub by disabling cross-region disaster recovery. '
                   'This property is immutable once set on the resource. Only available in select regions. '
                   'Learn more at https://aka.ms/iothubdisabledr')

    with self.argument_context('iot hub show-connection-string') as c:
        c.argument('show_all', options_list=['--all'], help='Allow to show all shared access policies.')
        c.argument('hub_name', options_list=['--hub-name', '--name', '-n'])
        c.argument('policy_name', help='Shared access policy to use.')
        c.argument('key_type', arg_type=get_enum_type(KeyType), options_list=['--key'], help='The key to use.')

    # Arguments for Message Enrichments
    with self.argument_context('iot hub message-enrichment') as c:
        c.argument('key', options_list=['--key', '-k'], help='The enrichment\'s key.')
        c.argument('value', options_list=['--value', '-v'], help='The enrichment\'s value.')
        c.argument('endpoints', options_list=['--endpoints', '-e'], nargs='*',
                   help='Endpoint(s) to apply enrichments to. Use a space-separated list for multiple endpoints.')
