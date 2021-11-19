# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from abc import ABC, abstractmethod
from azure.core.exceptions import HttpResponseError
from knack.util import CLIError
from knack.log import get_logger
from azext_iot.common.shared import AuthenticationTypeDataplane
from typing import Any, Dict, List
from types import SimpleNamespace

logger = get_logger(__name__)
POLICY_ERROR_TEMPLATE = (
    "Unable to discover a priviledged policy for {0}: {1}, in subscription {2}. "
    "When interfacing with an {0}, the IoT extension requires any single policy with "
    "{3} rights."
)


def _format_policy_set(inputs: set) -> str:
    inputs = list(f"'{x}'" for x in inputs)
    if len(inputs) == 1:
        return inputs[0]
    elif len(inputs) == 2:
        return inputs[0] + " and " + inputs[1]

    inputs[-1] = "and " + inputs[-1]
    return ", ".join(inputs)


# Abstract base class
class BaseDiscovery(ABC):
    """BaseDiscovery to support resource and policy auto discovery.

    Eliminates the need to provide the resource group and policy name to
    find a specific target resource.

    :ivar cmd: The cmd object
    :vartype cmd:

    :ivar client: The client object
    :vartype client:

    :ivar sub_id: Subscription id
    :vartype sub_id: str

    :ivar track2: Whether the client uses track2.
    :vartype track2: bool

    :ivar resource_type: Type of the resources the client fetches. Used to abstract
                         error messages.
    :vartype resource_type: DiscoveryResourceType

    :ivar necessary_rights_set: Set of policy names needed for the Iot Extension to run
                                commands against the DPS instance.
    :vartype necessary_rights_set: Set[str]
    """
    def __init__(self, cmd, necessary_rights_set: set = None, resource_type: str = None):
        self.cmd = cmd
        self.client = None
        self.sub_id = "unknown"
        self.resource_type = resource_type
        self.track2 = False
        self.necessary_rights_set = necessary_rights_set

    @abstractmethod
    def _initialize_client(self):
        """Creates the client if not created already."""
        pass

    @abstractmethod
    def _make_kwargs(self, **kwargs) -> Dict[str, Any]:
        """Returns the correct kwargs for the client operations."""
        pass

    def get_resources(self, rg: str = None) -> List:
        """
        Returns a list of all raw resources that are present within the subscription (and
        resource group if provided).

        The resources are the raw data returned by the client and will be used to build
        target objects.

        :param rg: Resource Group
        :type rg: str

        :return: List of resources
        :rtype: List
        """
        self._initialize_client()

        resource_list = []

        if not rg:
            resource_pager = self.client.list_by_subscription()
        else:
            resource_pager = self.client.list_by_resource_group(resource_group_name=rg)

        if self.track2:
            for resources in resource_pager.by_page():
                resource_list.extend(resources)
        else:
            try:
                while True:
                    resource_list.extend(resource_pager.advance_page())
            except StopIteration:
                pass

        return resource_list

    def get_policies(self, resource_name: str, rg: str) -> List:
        """
        Returns a list of all policies for a given resource in a given resource group.

        :param resource_name: Resource Name
        :type resource_name: str
        :param rg: Resource Group
        :type rg: str

        :return: List of policies
        :rtype: List
        """
        self._initialize_client()

        policy_pager = self.client.list_keys(
            **self._make_kwargs(resource_name=resource_name, resource_group_name=rg)
        )
        policy_list = []

        if self.track2:
            for policies in policy_pager.by_page():
                policy_list.extend(policies)
        else:
            try:
                while True:
                    policy_list.extend(policy_pager.advance_page())
            except StopIteration:
                pass

        return policy_list

    def find_resource(self, resource_name: str, rg: str = None):
        """
        Returns the resource with the given resource_name.

        If the resource group is not provided, will look through all resources within the
        subscription and return first match. This functionality will only work for
        resource types that require unique names within the subscription.

        Raises CLIError if no resource is found.

        :param resource_name: Resource Name
        :type resource_name: str
        :param rg: Resource Group
        :type rg: str

        :return: Resource
        :rtype: dict representing self.resource_type
        """
        self._initialize_client()

        if rg:
            try:
                return self.client.get(
                    **self._make_kwargs(
                        resource_name=resource_name, resource_group_name=rg
                    )
                )
            except:  # pylint: disable=broad-except
                raise CLIError(
                    "Unable to find {}: {} in resource group: {}".format(
                        self.resource_type, resource_name, rg
                    )
                )

        resource_list = self.get_resources()

        if resource_list:
            target = next(
                (resource for resource in resource_list if resource_name.lower() == resource.name.lower()),
                None
            )
            if target:
                return target

        raise CLIError(
            "Unable to find {}: {} in current subscription {}.".format(
                self.resource_type, resource_name, self.sub_id
            )
        )

    def find_policy(self, resource_name: str, rg: str, policy_name: str = "auto"):
        """
        Returns the policy with the policy_name for the given resource.

        If the policy name is not provided, will look through all policies for the given
        resource and return the first usable policy (the first policy that the IoT
        extension can use).

        Raises CLIError if no usable policy is found.

        :param resource_name: Resource Name
        :type resource_name: str
        :param rg: Resource Group
        :type rg: str
        :param policy_name: Policy Name
        :type policy_name: str

        :return: Policy
        :rtype: policy
        """
        self._initialize_client()

        if policy_name.lower() != "auto":
            return self.client.get_keys_for_key_name(
                **self._make_kwargs(
                    resource_name=resource_name,
                    resource_group_name=rg,
                    key_name=policy_name
                )
            )

        policy_list = self.get_policies(resource_name=resource_name, rg=rg)

        for policy in policy_list:
            rights_set = set(policy.rights.split(", "))
            if self.necessary_rights_set.issubset(rights_set):
                logger.info(
                    "Using policy '%s' for %s interaction.", policy.key_name, self.resource_type
                )
                return policy

        raise CLIError(
            POLICY_ERROR_TEMPLATE.format(
                self.resource_type,
                resource_name,
                self.sub_id,
                _format_policy_set(self.necessary_rights_set)
            )
        )

    @classmethod
    @abstractmethod
    def get_target_by_cstring(cls, connection_string):
        """Returns target inforation needed from a connection string."""
        pass

    def get_target(
        self, resource_name: str, resource_group_name: str = None, **kwargs
    ) -> Dict[str, str]:
        """
        Returns a dictionary of the given resource's connection string parts to be used
        by the extension.

        This function finds the target resource and builds up a dictionary of connection
        string parts needed for IoT extension operation. In future iteration we will
        return a 'Target' object rather than dict but that will be better served aligning
        with vNext pattern for Iot Hub/DPS.

        If the resource group is not provided, will look through all resources within the
        subscription and return first match. This functionality will only work for
        resource types that require unique names within the subscription.

        If the policy name is not provided, will look through all policies for the given
        resource and return the first usable policy (the first policy that the IoT
        extension can use).

        Raises CLIError if no resource is found.

        :param resource_name: Resource Name
        :type resource_name: str
        :param rg: Resource Group
        :type rg: str

        :keyword str login: Connection string for the target resource
        :keyword str key_type: Key type to use in connection string construction
        :keyword auth_type: Authentication Type for the Dataplane
        :paramtype auth_type: AuthenticationTypeDataplane
        :keyword str policy_name: Policy name to use

        :return: Resource
        :rtype: dict representing self.resource_type
        """
        cstring = kwargs.get("login")
        if cstring:
            return self.get_target_by_cstring(connection_string=cstring)

        resource_group_name = resource_group_name or kwargs.get("rg")
        resource = self.find_resource(resource_name=resource_name, rg=resource_group_name)

        key_type = kwargs.get("key_type", "primary")

        # Azure AD auth path
        auth_type = kwargs.get("auth_type", AuthenticationTypeDataplane.key.value)
        if auth_type == AuthenticationTypeDataplane.login.value:
            logger.info("Using AAD access token for %s interaction.", self.resource_type)
            policy = SimpleNamespace()
            policy.key_name = AuthenticationTypeDataplane.login.value
            policy.primary_key = AuthenticationTypeDataplane.login.value
            policy.secondary_key = AuthenticationTypeDataplane.login.value

            return self._build_target(
                resource=resource,
                policy=policy,
                key_type="primary",
                **kwargs
            )

        policy_name = kwargs.get("policy_name", "auto")
        rg = resource.additional_properties.get("resourcegroup")

        resource_policy = self.find_policy(
            resource_name=resource.name, rg=rg, policy_name=policy_name,
        )

        return self._build_target(
            resource=resource,
            policy=resource_policy,
            key_type=key_type,
            **kwargs
        )

    def get_targets(self, resource_group_name: str = None, **kwargs) -> List[Dict[str, str]]:
        """
        Returns a list of targets (dicts representing a resource's connection string parts)
        that are usable by the extension within the subscription (and resource group if
        provided).

        :param rg: Resource Group
        :type rg: str

        :return: Resources
        :rtype: list[dict]
        """
        targets = []
        resources = self.get_resources(rg=resource_group_name)
        if resources:
            for resource in resources:
                try:
                    targets.append(
                        self.get_target(
                            resource_name=resource.name,
                            resource_group_name=resource.additional_properties.get("resourcegroup"),
                            **kwargs
                        )
                    )
                except HttpResponseError as e:
                    logger.warning("Could not access %s. %s", resource, e)

        return targets

    @abstractmethod
    def _build_target(self, resource, policy, key_type=None, **kwargs):
        """Returns a dictionary representing the resource connection string parts to
        be used by the IoT extension."""
        pass
