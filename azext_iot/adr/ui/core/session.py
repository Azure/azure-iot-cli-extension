# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Session: scope, provider access and the error boundary.

The session is the only place the UI touches the Azure CLI context. Providers are
constructed once and reused, and every provider call goes through :meth:`Session.call`
so no exception can escape into the CLI's top-level handler while the UI owns the
terminal.

This module is deliberately free of any UI framework import.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

#: Provider classes by the name the kinds refer to them by. Imported lazily in
#: :meth:`Session.provider` so building a session stays cheap.
_PROVIDER_PATHS = {
    "namespace": ("azext_iot.adr.providers.namespace", "NamespaceProvider"),
    "registry_device": ("azext_iot.adr.providers.registry_device", "RegistryDeviceProvider"),
    "group": ("azext_iot.adr.providers.group", "GroupProvider"),
    "job": ("azext_iot.adr.providers.job", "JobProvider"),
    "job_run": ("azext_iot.adr.providers.job_run", "JobRunProvider"),
    "certificate_authority": (
        "azext_iot.adr.providers.certificate_authority",
        "CertificateAuthorityProvider",
    ),
    "certificate_policy": (
        "azext_iot.adr.providers.certificate_policy",
        "CertificatePolicyProvider",
    ),
    "link": ("azext_iot.adr.providers.link", "LinkProvider"),
    "update_instance": ("azext_iot.adr.providers.update_instance", "UpdateInstanceProvider"),
}


class SessionError(Exception):
    """A provider failure, already translated into something worth showing a user.

    Carries an optional ``detail`` (correlation ids, endpoint-level reasons) that the
    caller may surface in a dialog rather than the single-line flash.
    """

    def __init__(self, message: str, detail: Optional[str] = None, recoverable: bool = True):
        super().__init__(message)
        self.message = message
        self.detail = detail
        self.recoverable = recoverable

    def __str__(self) -> str:
        return self.message


def _http_status(error: Exception) -> Optional[int]:
    status = getattr(error, "status_code", None)
    return status if isinstance(status, int) else None


def translate_error(error: Exception) -> SessionError:
    """Turn a provider or SDK exception into a message a user can act on.

    Provider messages are already written for humans, so they are preserved verbatim;
    this only adds context for the failures that arrive as bare HTTP errors.
    """
    from azure.cli.core.azclierror import AzCLIError

    status = _http_status(error)
    text = str(error).strip() or error.__class__.__name__

    if isinstance(error, AzCLIError):
        # Argument, usage and not-found errors already carry actionable guidance.
        return SessionError(text)

    if status == 401 or status == 403:
        return SessionError(
            "Not authorized for this operation. Check your role assignments on the resource.",
            detail=text,
        )
    if status == 404:
        return SessionError("The resource was not found.", detail=text)
    if status == 429:
        return SessionError("The service is throttling requests. Backing off.", detail=text)
    if status is not None and status >= 500:
        return SessionError("The service reported an error. Retrying may succeed.", detail=text)

    return SessionError(text)


@dataclass
class Scope:
    """What the user is currently looking at.

    Kinds receive this as a plain mapping, so a spec's ``list`` callable needs no
    knowledge of the session.
    """

    subscription_id: Optional[str] = None
    subscription_name: Optional[str] = None
    resource_group_name: Optional[str] = None
    namespace_name: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        values = {
            "subscription": self.subscription_name or self.subscription_id,
            "subscription_id": self.subscription_id,
            "resource_group_name": self.resource_group_name,
            "namespace_name": self.namespace_name,
        }
        values.update(self.extra)
        return values


class Session:
    """Holds the CLI context, resolved scope and cached providers."""

    def __init__(self, cmd, resource_group_name: Optional[str] = None,
                 namespace_name: Optional[str] = None, read_only: bool = False):
        self.cmd = cmd
        self.read_only = read_only
        self._providers: Dict[str, Any] = {}
        self.scope = Scope(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
        )

    # -- scope -------------------------------------------------------------

    def resolve_subscription(self) -> Optional[str]:
        """Read the active subscription from the CLI profile. Never fatal."""
        if self.scope.subscription_id or self.cmd is None:
            return self.scope.subscription_id
        try:
            from azure.cli.core._profile import Profile

            subscription = Profile(cli_ctx=self.cmd.cli_ctx).get_subscription()
            self.scope.subscription_id = subscription.get("id")
            self.scope.subscription_name = subscription.get("name")
        except Exception:  # noqa: BLE001 - an unusable profile must not stop the UI
            return None
        return self.scope.subscription_id

    # -- providers ---------------------------------------------------------

    def provider(self, name: str):
        """Return a cached provider. Each constructor builds a client, so reuse matters."""
        if name not in self._providers:
            try:
                module_path, class_name = _PROVIDER_PATHS[name]
            except KeyError:
                raise SessionError(f"No provider is registered as '{name}'.") from None
            module = __import__(module_path, fromlist=[class_name])
            self._providers[name] = getattr(module, class_name)(self.cmd)
        return self._providers[name]

    # -- error boundary ----------------------------------------------------

    def call(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        """Invoke a provider method, translating every failure into ``SessionError``."""
        try:
            return func(*args, **kwargs)
        except SessionError:
            raise
        except Exception as error:  # noqa: BLE001 - this is the boundary
            raise translate_error(error) from error

    def list_from(self, provider_name: str, method_name: str, **kwargs) -> list:
        """Call a provider's list method through the boundary and normalise the result."""
        provider = self.provider(provider_name)
        method = getattr(provider, method_name, None)
        if method is None:
            raise SessionError(f"'{provider_name}' has no operation '{method_name}'.")
        result = self.call(method, **kwargs)
        if result is None:
            return []
        return list(result)
