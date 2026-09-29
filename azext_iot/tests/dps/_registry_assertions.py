# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Registry command assertions on the existing registration fixture's owned devices."""

from shlex import join, quote

from azext_iot.tests.adr._helpers import wait_for_condition
from azext_iot.tests.dps._csr_issuance import invoke

PREFIX = "iot adr ns device"
METADATA_TIMEOUT = 600
KEY_LENGTH_QUERY = "{primary:length(symmetricKey.primaryKey),secondary:length(symmetricKey.secondaryKey)}"


def _wait(fetch, condition, description):
    return wait_for_condition(
        fetch, condition, description=description, timeout=METADATA_TIMEOUT, interval=5,
        is_retryable_error=lambda _error: False,
    )


def _child_name(child, parent_id, collection):
    name = child["name"]
    assert isinstance(name, str) and name and name not in (".", "..")
    assert not any(character in name for character in "/\\?#%")
    assert child["id"].casefold() == f"{parent_id}/{collection}/{name}".casefold(), "Registry child scope changed."
    return name


def _profile(properties, authentication_type, policy_id):
    assert properties["authenticationType"] == authentication_type
    assert "symmetricKey" not in properties, "Metadata must not expose keys."
    if policy_id is not None:
        assert properties["certificateAuthority"]["certificatePolicyResourceId"].casefold() == policy_id.casefold()


def assert_registry_registration(resource, ownership, *, certificate):
    device = ownership.read_device()
    namespace = ownership.namespace
    properties = device["properties"]
    scope = join(["--ns", namespace["name"], "-g", namespace["resource_group"],
                  "--subscription", namespace["subscription"]])
    args = f"{scope} -n {quote(device['name'])}"
    invoke(f"{PREFIX} wait {args} --exists --timeout 600 --interval 5")
    for selector in (f"-n {quote(device['name'])}", f"--external-device-id {quote(properties['externalDeviceId'])}"):
        shown = invoke(f"{PREFIX} show {scope} {selector}").as_json()
        assert shown["id"].casefold() == device["id"].casefold()
        assert shown["properties"]["externalDeviceId"] == properties["externalDeviceId"]
        assert shown["properties"]["uuid"] == properties["uuid"]
    listed = invoke(f"{PREFIX} list {scope}").as_json()
    assert sum(item["id"].casefold() == device["id"].casefold() for item in listed) == 1

    hub = resource["hub"]
    identity = _wait(
        lambda: invoke(
            f"iot hub device-identity show -n {quote(hub['name'])} -g {quote(hub['rg'])} "
            f"-d {quote(ownership.intent['device_id'])} --auth-type login --subscription {namespace['subscription']} "
            "--query '{deviceId:deviceId,uuid:adrDeviceProperties.uuid,authType:authentication.type}'"
        ).as_json(),
        lambda value: bool(value["uuid"]), "owned Hub RegistryDevice metadata",
    )
    assert identity["deviceId"] == ownership.intent["device_id"]
    assert isinstance(properties["uuid"], str) and properties["uuid"]
    assert identity["uuid"].casefold() == properties["uuid"].casefold()
    authentication_type = "CertificateAuthoritySignedX509Certificate" if certificate else "SymmetricKey"
    policy_id = (
        f"{namespace['id']}/certificateAuthorities/{resource['ca']}/certificatePolicies/{resource['policy']}"
        if certificate else None
    )
    child_args = f"{scope} --rdn {quote(device['name'])}"

    def profiles():
        values = invoke(f"{PREFIX} auth list {child_args}").as_json()
        matches = [value for value in values if value["properties"]["authenticationType"] == authentication_type]
        assert len(matches) <= 1, "Ambiguous owned authentication profile."
        return matches

    profile = _wait(profiles, bool, "owned RegistryDevice authentication profile")[0]
    profile_name = _child_name(profile, device["id"], "authenticationProfiles")
    _profile(profile["properties"], authentication_type, policy_id)
    profile_args = f"{child_args} -n {quote(profile_name)}"
    invoke(f"{PREFIX} auth wait {profile_args} --exists --timeout 600 --interval 5")

    def show_profile():
        shown = invoke(f"{PREFIX} auth show {profile_args}").as_json()
        assert shown["id"].casefold() == profile["id"].casefold()
        _profile(shown["properties"], authentication_type, policy_id)

    show_profile()

    def fetch_capabilities():
        values = invoke(f"{PREFIX} capability list {child_args}").as_json()
        matches = [
            value for value in values if value["properties"]["capabilityType"] == "Microsoft.IoTHub"
            and value["properties"]["authenticationProfileResourceId"].casefold() == profile["id"].casefold()
        ]
        for value in matches:
            assert value["properties"]["provisioningState"] != "Failed", "Registry capability provisioning failed."
        return matches

    capabilities = _wait(
        fetch_capabilities, lambda values: bool(values) and all(
            value["properties"]["provisioningState"] == "Succeeded" for value in values
        ), "owned RegistryDevice Hub capability",
    )
    for capability in capabilities:
        name = _child_name(capability, device["id"], "capabilities")
        shown = invoke(f"{PREFIX} capability show {child_args} -n {quote(name)}").as_json()
        assert shown["id"].casefold() == capability["id"].casefold()
        assert shown["properties"]["capabilityType"] == "Microsoft.IoTHub"
        assert shown["properties"]["authenticationProfileResourceId"].casefold() == profile["id"].casefold()
        assert shown["properties"]["provisioningState"] == "Succeeded"
    ownership.read_device()
    show_profile()
    if certificate:
        # The profile GET contract has no revocation generation/operation marker.
        # Keeping the profile, changing its ETag, or receiving 202 is NOT CRL
        # invalidation evidence. Keep the waited action and quarantine on *any*
        # error (including denied subscription-regional status reads).
        with ownership.certificate_revocation(profile["id"]):
            invoke(f"{PREFIX} auth revoke-certs {profile_args} --yes --output none")
        show_profile()
    else:
        assert identity["authType"] == "sas"
        lengths = invoke(f"{PREFIX} auth show-keys {profile_args} --query {quote(KEY_LENGTH_QUERY)}").as_json()
        assert set(lengths) == {"primary", "secondary"}
        assert all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in lengths.values())
