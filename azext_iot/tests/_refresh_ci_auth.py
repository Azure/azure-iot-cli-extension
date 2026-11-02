# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Refresh CI's CLI credential caches, never ACCOUNT/azureProfile.json.

Run from the checkout with the service's tox Python and inherited AZURE_CONFIG_DIR.
Initial azure/login and subscription selection must finish before this runs. Unlike
``az login``, Identity.login_with_service_principal does not discover subscriptions
or save ACCOUNT. CLI's SecretStore locks saves/retries reads; MSAL's persisted cache
handles concurrent token access. Do not add a separate profile/cache locking scheme.

New CLI credential lookups reload the SP store even in long-lived processes.
An existing SDK credential can consume renewed tokens from MSAL's shared cache,
but retains its original assertion on a cache miss for another resource. This
credential-object lifetime limit also applies to periodic ``az login``.
"""

import argparse
import json
import logging
import os
from pathlib import Path
import signal
import sys
from threading import Event
from types import SimpleNamespace

import requests


HTTP_TIMEOUT = (10, 30)


def refresh():
    # Use the installed CLI's cloud/config and persistence implementations, but not
    # AzCli initialization: Session.load can overwrite even a malformed profile.
    from azure.cli.core._environment import get_config_dir
    from azure.cli.core._profile import _create_identity_instance
    from azure.cli.core.auth.identity import ServicePrincipalAuth
    from azure.cli.core.auth.msal_credentials import ServicePrincipalCredential
    from azure.cli.core.auth.util import resource_to_scopes
    from azure.cli.core.cloud import get_active_cloud_name, get_cloud
    from knack.config import CLIConfig

    client, tenant, subscription = (
        os.environ[name] for name in ("AZURE_CLIENT_ID", "AZURE_TENANT_ID", "TEST_SUBSCRIPTION_ID")
    )
    if not all(value.strip() for value in (client, tenant, subscription)):
        raise ValueError("Explicit client, tenant and subscription are required.")
    config_dir = get_config_dir()
    profile_path = Path(config_dir) / "azureProfile.json"
    before = profile_path.read_bytes()
    profile = json.loads(before.decode("utf-8-sig"))
    cli_ctx = SimpleNamespace(config=CLIConfig(config_dir=config_dir, config_env_var_prefix="AZURE"))
    cli_ctx.cloud = get_cloud(cli_ctx, get_active_cloud_name(cli_ctx))
    accounts = [
        account for account in profile["subscriptions"]
        if account.get("isDefault") and account.get("environmentName") == cli_ctx.cloud.name
    ]
    if len(accounts) != 1:
        raise ValueError("Exactly one current account in the active cloud is required.")
    account = accounts[0]
    user = account.get("user", {})
    if (
        account["id"].lower() != subscription.lower()
        or account["tenantId"].lower() != tenant.lower()
        or user.get("type") != "servicePrincipal"
        or user.get("name", "").lower() != client.lower()
    ):
        raise ValueError("Current account does not match the explicit subscription, tenant and service principal.")
    # Store keys are case-sensitive even though GUID identity comparisons are not.
    # Use exactly the keys a fresh CLI consumer will read from this account.
    client, tenant = user["name"], account["tenantId"]

    # No tokens in argv, stdout or shell substitutions; the entrypoint sanitizes errors.
    with requests.get(
        os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"],
        params={"audience": "api://AzureADTokenExchange"},
        headers={"Authorization": "bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]},
        timeout=HTTP_TIMEOUT,
        allow_redirects=False,
    ) as response:
        if response.status_code != 200:
            raise RuntimeError("GitHub OIDC token request failed.")
        assertion = response.json()["value"]
    if not isinstance(assertion, str) or not assertion.strip():
        raise ValueError("GitHub OIDC response has no assertion.")
    identity = _create_identity_instance(cli_ctx, cli_ctx.cloud.endpoints.active_directory, tenant_id=tenant)
    # Mirror Identity.login_with_service_principal: that method cannot pass a
    # timeout, leaving MSAL's discovery and token HTTP requests unbounded.
    # Keep CLI's cache/config kwargs and persist the SP only after token success.
    sp_auth = ServicePrincipalAuth.build_from_credential(
        identity.tenant_id, client, ServicePrincipalAuth.build_credential(client_assertion=assertion),
    )
    credential = ServicePrincipalCredential(
        client, sp_auth.get_msal_client_credential(), timeout=HTTP_TIMEOUT,
        **identity._msal_app_kwargs,  # pylint: disable=protected-access
    )
    credential.acquire_token(resource_to_scopes(cli_ctx.cloud.endpoints.active_directory_resource_id))
    identity._service_principal_store.save_entry(sp_auth.get_entry_to_persist())  # pylint: disable=protected-access
    if profile_path.read_bytes() != before:
        raise RuntimeError("Azure account profile changed during credential refresh.")
    print("OIDC CLI credential caches refreshed; account profile unchanged.", flush=True)


def report_failure(exc_type, _exception, _traceback):
    # requests/CLI exceptions can include token URLs, assertions or response bodies.
    # Keep a failing exit status, but never render their values or a traceback.
    print(f"::error::OIDC CLI credential refresh failed ({exc_type.__name__}); integration auth is unhealthy.",
          file=sys.stderr, flush=True)


def main():
    sys.excepthook = report_failure
    # This is a dedicated auth process: even user-configured HTTP debug logs must
    # not expose credentials. Unexpected errors still exit nonzero via excepthook.
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop", action="store_true", help="Refresh every 240 seconds after a successful preflight run.")
    parser.add_argument("--ready-file", type=Path, help="Mark loop readiness after installing shutdown handlers.")
    args = parser.parse_args()
    if args.ready_file and not args.loop:
        parser.error("--ready-file requires --loop")
    if not args.loop:
        refresh()
        return
    stopped = Event()
    # Finish an in-flight cache write before exiting; never kill the cache writer
    # halfway through persistence just because the tests have finished.
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    if args.ready_file:
        args.ready_file.write_text("ready\n", encoding="ascii")
    while not stopped.wait(240):
        refresh()


if __name__ == "__main__":
    main()
