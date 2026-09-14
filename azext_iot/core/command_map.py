# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core.commands import CliCommandType, LongRunningOperation

from azext_iot._factory import iot_hub_service_factory, iot_service_provisioning_factory
from azure.cli.command_modules.iot._utils import _dps_certificate_response_transform

# Command types for both IoT Hub and DPS management operations
core_ops = CliCommandType(operations_tmpl="azext_iot.core.custom#{}")

# Constants
CS_DEPRECATION_INFO = 'IoT Extension (azure-iot) connection-string command (az iot hub connection-string show)'
ROUTE_DEPRECATION_INFO = 'IoT Extension (azure-iot) message-route command group (az iot hub message-route)'
ENDPOINT_DEPRECATION_INFO = 'IoT Extension (azure-iot) message-endpoint command group (az iot hub message-endpoint)'


class PolicyUpdateResultTransform(LongRunningOperation):  # pylint: disable=too-few-public-methods
    def __call__(self, poller):
        result = super().__call__(poller)
        return result["properties"]["authorizationPolicies"]


class EndpointUpdateResultTransform(LongRunningOperation):  # pylint: disable=too-few-public-methods
    def __call__(self, poller):
        result = super().__call__(poller)
        return result["properties"]["routing"]["endpoints"]


class RouteUpdateResultTransform(LongRunningOperation):  # pylint: disable=too-few-public-methods
    def __call__(self, poller):
        result = super().__call__(poller)
        return result["properties"]["routing"]["routes"]


# Deleting IoT Hub is a long-running operation. Due to API implementation issue, 404 error will be thrown during
# deletion of an IoT Hub.
# This is a work around to suppress the 404 error. It should be removed after API is fixed.
class HubDeleteResultTransform(LongRunningOperation):  # pylint: disable=too-few-public-methods
    def __call__(self, poller):
        from azure.cli.core.util import CLIError
        # if no wait, return right away
        if not poller:
            return poller
        try:
            super().__call__(poller)
        except CLIError as e:
            if 'not found' not in str(e):
                raise e


def load_core_commands(self, _):
    """
    Load CLI commands for both IoT Hub and DPS management
    """
    # iot hub commands
    with self.command_group(
        "iot hub", command_type=core_ops, client_factory=iot_hub_service_factory
    ) as cmd_group:
        cmd_group.command("create", "iot_hub_create", supports_no_wait=True)
        cmd_group.generic_update_command(
            "update",
            getter_name="iot_hub_get",
            setter_name="iot_hub_update",
            custom_func_type=core_ops,
            custom_func_name="update_iot_hub_custom",
        )
        cmd_group.command("delete", "iot_hub_delete", supports_no_wait=True)
        cmd_group.show_command("show", "iot_hub_get")
        cmd_group.command("list", "iot_hub_list")
        cmd_group.command('list-skus', 'iot_hub_sku_list')
        cmd_group.command('show-quota-metrics', 'iot_hub_get_quota_metrics')
        cmd_group.command('show-stats', 'iot_hub_get_stats')
        cmd_group.command('manual-failover', 'iot_hub_manual_failover', supports_no_wait=True)

    # iot hub certificate commands
    with self.command_group('iot hub certificate', command_type=core_ops, client_factory=iot_hub_service_factory) as g:
        g.command(
            'list', 'iot_hub_certificate_list',
            table_transformer=(
                "value[*].{Name:name,ResourceGroup:resourceGroup,Created:properties.created,Expiry:properties.expiry,"
                "Subject:properties.subject,Thumbprint:properties.thumbprint,IsVerified:properties.isVerified}"
            )
        )
        g.show_command('show', 'iot_hub_certificate_get')
        g.command('create', 'iot_hub_certificate_create')
        g.command('delete', 'iot_hub_certificate_delete')
        g.command('generate-verification-code', 'iot_hub_certificate_gen_code')
        g.command('verify', 'iot_hub_certificate_verify')
        g.command('update', 'iot_hub_certificate_update')

    # iot hub consumer group commands
    with self.command_group('iot hub consumer-group', command_type=core_ops, client_factory=iot_hub_service_factory) as g:
        g.command('create', 'iot_hub_consumer_group_create')
        g.command('list', 'iot_hub_consumer_group_list')
        g.show_command('show', 'iot_hub_consumer_group_get')
        g.command('delete', 'iot_hub_consumer_group_delete')

    # iot hub identity commands
    with self.command_group('iot hub identity', command_type=core_ops, client_factory=iot_hub_service_factory) as g:
        g.command('assign', 'iot_hub_identity_assign')
        g.show_command('show', 'iot_hub_identity_show')
        g.command('remove', 'iot_hub_identity_remove')

    # iot hub policy commands
    with self.command_group('iot hub policy', command_type=core_ops, client_factory=iot_hub_service_factory) as g:
        g.command('list', 'iot_hub_policy_list')
        g.show_command('show', 'iot_hub_policy_get')
        g.command('create', 'iot_hub_policy_create', transform=PolicyUpdateResultTransform(self.cli_ctx))
        g.command('delete', 'iot_hub_policy_delete', transform=PolicyUpdateResultTransform(self.cli_ctx))
        g.command('renew-key', 'iot_hub_policy_key_renew', supports_no_wait=True)

    # iot hub routing endpoint commands
    with self.command_group('iot hub routing-endpoint', command_type=core_ops, client_factory=iot_hub_service_factory,
                            deprecate_info=self.deprecate(redirect=ENDPOINT_DEPRECATION_INFO, hide=True)) as g:
        g.command('create', 'iot_hub_routing_endpoint_create',
                  transform=EndpointUpdateResultTransform(self.cli_ctx))
        g.show_command('show', 'iot_hub_routing_endpoint_show')
        g.command('list', 'iot_hub_routing_endpoint_list')
        g.command('delete', 'iot_hub_routing_endpoint_delete',
                  transform=EndpointUpdateResultTransform(self.cli_ctx))

    # iot hub message enrichment commands
    with self.command_group('iot hub message-enrichment', command_type=core_ops,
                            client_factory=iot_hub_service_factory) as g:
        g.command('create', 'iot_message_enrichment_create')
        g.command('list', 'iot_message_enrichment_list')
        g.command('delete', 'iot_message_enrichment_delete')
        g.command('update', 'iot_message_enrichment_update')

    # iot hub route commands
    with self.command_group('iot hub route', command_type=core_ops, client_factory=iot_hub_service_factory,
                            deprecate_info=self.deprecate(redirect=ROUTE_DEPRECATION_INFO, hide=True)) as g:
        g.command('create', 'iot_hub_route_create', transform=RouteUpdateResultTransform(self.cli_ctx))
        g.show_command('show', 'iot_hub_route_show')
        g.command('list', 'iot_hub_route_list')
        g.command('delete', 'iot_hub_route_delete', transform=RouteUpdateResultTransform(self.cli_ctx))
        g.command('update', 'iot_hub_route_update', transform=RouteUpdateResultTransform(self.cli_ctx))
        g.command('test', 'iot_hub_route_test')

    # iot dps commands
    with self.command_group(
        "iot dps", command_type=core_ops, client_factory=iot_service_provisioning_factory
    ) as cmd_group:
        cmd_group.command("create", "iot_dps_create")
        cmd_group.generic_update_command(
            "update",
            getter_name="iot_dps_get",
            setter_name="iot_dps_update",
            custom_func_type=core_ops,
        )
        cmd_group.show_command("show", "iot_dps_get")
        cmd_group.command("delete", "iot_dps_delete")
        cmd_group.command("list", "iot_dps_list")

    # iot dps identity commands
    with self.command_group(
        "iot dps identity", command_type=core_ops, client_factory=iot_service_provisioning_factory
    ) as cmd_group:
        cmd_group.command("assign", "dps_identity_assign")
        cmd_group.command("remove", "dps_identity_remove")
        cmd_group.show_command("show", "dps_identity_show")

    # iot dps linked-hub commands
    with self.command_group('iot dps linked-hub', command_type=core_ops, client_factory=iot_service_provisioning_factory) as g:
        g.command('list', 'iot_dps_linked_hub_list')
        g.show_command('show', 'iot_dps_linked_hub_get')
        g.command('create', 'iot_dps_linked_hub_create', supports_no_wait=True)
        g.command('update', 'iot_dps_linked_hub_update', supports_no_wait=True)
        g.command('delete', 'iot_dps_linked_hub_delete', supports_no_wait=True)

    # iot dps certificate commands
    with self.command_group('iot dps certificate',
                            command_type=core_ops,
                            client_factory=iot_service_provisioning_factory,
                            transform=_dps_certificate_response_transform) as g:
        g.command(
            'list', 'iot_dps_certificate_list',
            table_transformer=(
                "value[*].{Name:name,ResourceGroup:resourceGroup,Created:properties.created,Expiry:properties.expiry,"
                "Subject:properties.subject,Thumbprint:properties.thumbprint,IsVerified:properties.isVerified}"
            )
        )
        g.show_command('show', 'iot_dps_certificate_get')
        g.command('create', 'iot_dps_certificate_create')
        g.command('delete', 'iot_dps_certificate_delete')
        g.command('generate-verification-code', 'iot_dps_certificate_gen_code')
        g.command('verify', 'iot_dps_certificate_verify')
        g.command('update', 'iot_dps_certificate_update')

    # iot dps policy commands
    with self.command_group('iot dps policy', command_type=core_ops, client_factory=iot_service_provisioning_factory) as g:
        g.command('list', 'iot_dps_policy_list')
        g.show_command('show', 'iot_dps_policy_get')
        g.command('create', 'iot_dps_policy_create', supports_no_wait=True)
        g.command('update', 'iot_dps_policy_update', supports_no_wait=True)
        g.command('delete', 'iot_dps_policy_delete', supports_no_wait=True)
