# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger
from azext_iot.common.utility import handle_service_exception
from azext_iot.deviceupdate.common import (
    ADUPublicNetworkAccessType,
    ADUAccountSKUType
)
from azext_iot.deviceupdate.providers.base import (
    DeviceUpdateMgmtModels,
    DeviceUpdateAccountManager,
    parse_account_rg,
    ARMPolling,
)

logger = get_logger(__name__)

# Accounts


def create_account(
    cmd,
    name,
    resource_group_name,
    location=None,
    tags=None,
    public_network_access=ADUPublicNetworkAccessType.ENABLED.value,
    assign_identity=None,
    scopes=None,
    role="Contributor",
    sku=ADUAccountSKUType.STANDARD.value,
):
    account_manager = DeviceUpdateAccountManager(cmd=cmd)
    if not location:
        location = account_manager.get_rg_location(
            resource_group_name=resource_group_name
        )

    account_manager = DeviceUpdateAccountManager(cmd=cmd)
    identity = account_manager.assemble_account_auth(assign_identity)
    account = DeviceUpdateMgmtModels.Account(
        location=location,
        tags=tags,
        public_network_access=public_network_access,
        identity=identity,
        sku=sku
    )

    def rbac_handler(lro: ARMPolling):
        if not scopes:
            return

        instance = lro.resource().as_dict()
        identity = instance.get("identity", {})
        if identity:
            identity_type: str = identity.get("type")
            principal_id: str = identity.get("principal_id")

            if (
                principal_id
                and scopes
                and identity_type
                and "SystemAssigned" in identity_type
            ):
                for scope in scopes:
                    logger.info(
                        "Applying rbac assignment: Principal Id: {}, Scope: {}, Role: {}".format(
                            principal_id, scope, role
                        )
                    )
                    logger.info(
                        account_manager.assign_msi_scope(
                            scope=scope, principal_id=principal_id, role=role
                        )
                    )

    try:
        create_poller = account_manager.mgmt_client.accounts.begin_create(
            resource_group_name=resource_group_name, account_name=name, account=account
        )
        create_poller.add_done_callback(rbac_handler)
        return create_poller
    except Exception as e:
        handle_service_exception(e)


def update_account(cmd, parameters: DeviceUpdateMgmtModels.Account):
    account_manager = DeviceUpdateAccountManager(cmd=cmd)

    # Supported update operations are PUT or PATCH based. CLI wise we are supporting only PUT.
    try:
        return account_manager.mgmt_client.accounts.begin_create(
            resource_group_name=parse_account_rg(parameters.id),
            account_name=parameters.name,
            account=parameters,
        )
    except Exception as e:
        handle_service_exception(e)


def list_accounts(cmd, resource_group_name=None):
    account_manager = DeviceUpdateAccountManager(cmd=cmd)
    if resource_group_name:
        return account_manager.mgmt_client.accounts.list_by_resource_group(
            resource_group_name=resource_group_name
        )
    return account_manager.mgmt_client.accounts.list_by_subscription()


def show_account(cmd, name, resource_group_name=None):
    account_manager = DeviceUpdateAccountManager(cmd=cmd)
    return account_manager.find_account(
        target_name=name, target_rg=resource_group_name
    ).account


def delete_account(cmd, name, resource_group_name=None):
    account_manager = DeviceUpdateAccountManager(cmd=cmd)
    account_container = account_manager.find_account(
        target_name=name, target_rg=resource_group_name
    )
    try:
        return account_manager.mgmt_client.accounts.begin_delete(
            resource_group_name=account_container.resource_group, account_name=name
        )
    except Exception as e:
        handle_service_exception(e)


# Account Networks - private connections


def show_account_private_connection(cmd, name, conn_name, resource_group_name=None):
    account_manager = DeviceUpdateAccountManager(cmd=cmd)
    account_container = account_manager.find_account(
        target_name=name, target_rg=resource_group_name
    )
    try:
        return account_manager.mgmt_client.private_endpoint_connections.get(
            resource_group_name=account_container.resource_group,
            account_name=name,
            private_endpoint_connection_name=conn_name,
        )
    except Exception as e:
        handle_service_exception(e)


def list_account_private_connections(cmd, name, resource_group_name=None):
    account_manager = DeviceUpdateAccountManager(cmd=cmd)
    account_container = account_manager.find_account(
        target_name=name, target_rg=resource_group_name
    )
    return account_manager.mgmt_client.private_endpoint_connections.list_by_account(
        resource_group_name=account_container.resource_group, account_name=name
    )


def set_account_private_connection(
    cmd,
    name,
    conn_name,
    status,
    description=None,
    resource_group_name=None,
):
    account_manager = DeviceUpdateAccountManager(cmd=cmd)
    account_container = account_manager.find_account(
        target_name=name, target_rg=resource_group_name
    )
    try:
        return account_manager.mgmt_client.private_endpoint_connections.begin_create_or_update(
            resource_group_name=account_container.resource_group,
            account_name=name,
            private_endpoint_connection_name=conn_name,
            private_endpoint_connection=DeviceUpdateMgmtModels.PrivateEndpointConnection(
                private_link_service_connection_state=DeviceUpdateMgmtModels.PrivateLinkServiceConnectionState(
                    status=status, description=description
                )
            ),
        )
    except Exception as e:
        handle_service_exception(e)


def delete_account_private_connection(
    cmd,
    name,
    conn_name,
    resource_group_name=None,
):
    account_manager = DeviceUpdateAccountManager(cmd=cmd)
    account_container = account_manager.find_account(
        target_name=name, target_rg=resource_group_name
    )
    try:
        return account_manager.mgmt_client.private_endpoint_connections.begin_delete(
            resource_group_name=account_container.resource_group,
            account_name=name,
            private_endpoint_connection_name=conn_name,
        )
    except Exception as e:
        handle_service_exception(e)


# Account Networks - private links


def list_account_private_links(cmd, name, resource_group_name=None):
    account_manager = DeviceUpdateAccountManager(cmd=cmd)
    account_container = account_manager.find_account(
        target_name=name, target_rg=resource_group_name
    )
    return account_manager.mgmt_client.private_link_resources.list_by_account(
        resource_group_name=account_container.resource_group, account_name=name
    )


def wait_on_account(cmd, name, resource_group_name=None):
    return show_account(cmd=cmd, name=name, resource_group_name=resource_group_name)
