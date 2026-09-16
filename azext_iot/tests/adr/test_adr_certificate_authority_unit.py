# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import errno
from unittest.mock import Mock

import pytest
from knack.util import CLIError
from azure.cli.core.azclierror import (
    ArgumentUsageError,
    AzureResponseError,
    FileOperationError,
    RequiredArgumentMissingError,
)

from azext_iot.adr import commands_certificate_authority as commands

_SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture(autouse=True)
def _patch_subscription_id(monkeypatch):
    monkeypatch.setattr(
        "azext_iot.adr.providers.certificate_authority.get_subscription_id",
        lambda _ctx: _SUBSCRIPTION_ID,
    )


@pytest.mark.parametrize("file_kind", ["missing", "directory"])
def test_activate_file_errors_precede_provider_creation(mocker, tmp_path, file_kind):
    path = tmp_path / "certificate-chain.pem"
    if file_kind == "directory":
        path.mkdir()
    provider = mocker.patch.object(commands, "CertificateAuthorityProvider")

    with pytest.raises(FileOperationError) as raised:
        commands.adr_ca_activate(Mock(), "ca", "ns", "rg", str(path))

    assert str(path) in str(raised.value)
    assert isinstance(raised.value.__cause__, OSError)
    provider.assert_not_called()


def test_activate_unreadable_file_preserves_the_os_reason(mocker):
    error = PermissionError(errno.EACCES, "Permission denied", "chain.pem")
    mocker.patch("azext_iot.common.utility.read_file_content", side_effect=error)
    provider = mocker.patch.object(commands, "CertificateAuthorityProvider")

    with pytest.raises(FileOperationError, match="Permission denied") as raised:
        commands.adr_ca_activate(Mock(), "ca", "ns", "rg", "chain.pem")

    assert raised.value.__cause__ is error
    provider.assert_not_called()


def test_activate_file_success_preserves_content_and_options(mocker, tmp_path):
    path = tmp_path / "certificate-chain.pem"
    path.write_text("certificate chain\n", encoding="utf-8")
    provider = mocker.patch.object(commands, "CertificateAuthorityProvider")
    cmd = Mock()

    result = commands.adr_ca_activate(cmd, "ca", "ns", "rg", str(path), no_wait=True)

    provider.assert_called_once_with(cmd)
    provider.return_value.activate.assert_called_once_with(
        certificate_authority_name="ca",
        namespace_name="ns",
        resource_group_name="rg",
        certificate_chain="certificate chain\n",
        no_wait=True,
    )
    assert result is provider.return_value.activate.return_value


# ==================== Create ====================


@pytest.mark.parametrize(
    "ca_type, issuer_type, issuer_ca_name, key_type, location",
    [
        ("Root", None, None, "ECC", None),
        ("ICA", "Microsoft", "myRootCA", None, "westus"),
        ("ICA", "External", None, "ECC", "eastus"),
    ],
    ids=["root-default-keytype", "microsoft-ica", "external-ica"],
)
def test_create_ca(
    fixture_ca_provider, mock_poller, ca_type, issuer_type, issuer_ca_name, key_type, location
):
    """CA creation builds the expected resource body and resolves location."""
    sentinel = Mock()
    fixture_ca_provider.client.certificate_authorities.begin_create_or_replace.return_value = mock_poller(
        sentinel
    )
    fixture_ca_provider.client.namespaces.get.return_value = {"location": "eastus"}

    result = fixture_ca_provider.create(
        certificate_authority_name="ca",
        namespace_name="ns",
        resource_group_name="rg",
        certificate_authority_type=ca_type,
        issuer_type=issuer_type,
        issuer_certificate_authority_name=issuer_ca_name,
        key_type=key_type,
        location=location,
    )

    assert result == sentinel
    call = fixture_ca_provider.client.certificate_authorities.begin_create_or_replace.call_args[1]
    resource = call["resource"]
    assert resource["properties"]["certificateAuthorityType"] == ca_type
    assert resource["properties"]["keyType"] == (key_type or "ECC")
    if issuer_type:
        assert resource["properties"]["issuer"]["issuerType"] == issuer_type
        if issuer_ca_name:
            assert resource["properties"]["issuer"][
                "certificateAuthorityResourceId"
            ].endswith(
                f"/providers/Microsoft.DeviceRegistry/namespaces/ns"
                f"/certificateAuthorities/{issuer_ca_name}"
            )
        else:
            assert "certificateAuthorityResourceId" not in resource["properties"]["issuer"]
    else:
        assert "issuer" not in resource["properties"]
    assert resource["location"] == (location or "eastus")
    # location resolved from namespace only when not provided
    if location is None:
        fixture_ca_provider.client.namespaces.get.assert_called_once()
    else:
        fixture_ca_provider.client.namespaces.get.assert_not_called()


def test_create_ca_with_tags(fixture_ca_provider, mock_poller):
    """CA creation forwards tags in the resource body."""
    fixture_ca_provider.client.certificate_authorities.begin_create_or_replace.return_value = mock_poller(
        Mock()
    )

    fixture_ca_provider.create(
        certificate_authority_name="ca",
        namespace_name="ns",
        resource_group_name="rg",
        certificate_authority_type="Root",
        location="eastus",
        tags={"env": "test"},
    )

    resource = fixture_ca_provider.client.certificate_authorities.begin_create_or_replace.call_args[1][
        "resource"
    ]
    assert resource["tags"] == {"env": "test"}


def test_create_ca_namespace_missing_location(fixture_ca_provider):
    """Create raises when location is omitted and the namespace has none."""
    fixture_ca_provider.client.namespaces.get.return_value = {}

    with pytest.raises(AzureResponseError, match=r"location"):
        fixture_ca_provider.create(
            certificate_authority_name="ca",
            namespace_name="ns",
            resource_group_name="rg",
            certificate_authority_type="Root",
        )
    fixture_ca_provider.client.certificate_authorities.begin_create_or_replace.assert_not_called()


def test_create_ica_requires_issuer_type(fixture_ca_provider):
    with pytest.raises(RequiredArgumentMissingError, match="issuer-type"):
        fixture_ca_provider.create(
            certificate_authority_name="ca",
            namespace_name="ns",
            resource_group_name="rg",
            certificate_authority_type="ICA",
            location="eastus",
        )


def test_create_microsoft_ica_requires_issuer_ca_name(fixture_ca_provider):
    with pytest.raises(RequiredArgumentMissingError, match="issuer-ca-name"):
        fixture_ca_provider.create(
            certificate_authority_name="ca",
            namespace_name="ns",
            resource_group_name="rg",
            certificate_authority_type="ICA",
            issuer_type="Microsoft",
            location="eastus",
        )


def test_create_root_rejects_issuer(fixture_ca_provider):
    with pytest.raises(ArgumentUsageError, match="only valid when --type ICA"):
        fixture_ca_provider.create(
            certificate_authority_name="ca",
            namespace_name="ns",
            resource_group_name="rg",
            certificate_authority_type="Root",
            issuer_type="External",
            location="eastus",
        )


@pytest.mark.parametrize(
    "ca_type,issuer_type,issuer_ca_name,match",
    [
        ("ICA", "External", "myRootCA", "cannot be used"),
        ("ICA", "Unknown", None, "either Microsoft or External"),
        ("Unknown", None, None, "either Root or ICA"),
    ],
)
def test_create_ca_rejects_invalid_issuer_combinations(
    fixture_ca_provider,
    ca_type,
    issuer_type,
    issuer_ca_name,
    match,
):
    with pytest.raises(ArgumentUsageError, match=match):
        fixture_ca_provider.create(
            certificate_authority_name="ca",
            namespace_name="ns",
            resource_group_name="rg",
            certificate_authority_type=ca_type,
            issuer_type=issuer_type,
            issuer_certificate_authority_name=issuer_ca_name,
            location="eastus",
        )

    fixture_ca_provider.client.certificate_authorities.begin_create_or_replace.assert_not_called()


# ==================== Show / List ====================


def test_show_ca(fixture_ca_provider):
    """Show returns the certificate authority resource."""
    fixture_ca_provider.client.certificate_authorities.get.return_value = {"name": "ca"}

    result = fixture_ca_provider.show(
        certificate_authority_name="ca", namespace_name="ns", resource_group_name="rg",
    )

    assert result["name"] == "ca"
    fixture_ca_provider.client.certificate_authorities.get.assert_called_once_with(
        resource_group_name="rg", namespace_name="ns", certificate_authority_name="ca",
    )


def test_list_ca(fixture_ca_provider):
    """List returns the certificate authorities as a list."""
    fixture_ca_provider.client.certificate_authorities.list_by_namespace.return_value = iter(
        [{"name": "ca1"}, {"name": "ca2"}]
    )

    result = fixture_ca_provider.list(namespace_name="ns", resource_group_name="rg")

    assert [r["name"] for r in result] == ["ca1", "ca2"]
    fixture_ca_provider.client.certificate_authorities.list_by_namespace.assert_called_once_with(
        resource_group_name="rg", namespace_name="ns",
    )


# ==================== Update ====================


def test_update_ca_with_tags(fixture_ca_provider, mock_poller):
    """Update sends tags and then fetches fresh state via show()."""
    fixture_ca_provider.client.certificate_authorities.begin_update.return_value = mock_poller(Mock())
    fixture_ca_provider.client.certificate_authorities.get.return_value = {"name": "ca"}

    result = fixture_ca_provider.update(
        certificate_authority_name="ca", namespace_name="ns", resource_group_name="rg",
        tags={"env": "prod"},
    )

    assert result["name"] == "ca"
    properties = fixture_ca_provider.client.certificate_authorities.begin_update.call_args[1]["properties"]
    assert properties["tags"] == {"env": "prod"}


# ==================== Delete ====================


def test_delete_ca(fixture_ca_provider, mock_poller):
    """Delete triggers begin_delete LRO and returns the result."""
    sentinel = Mock()
    fixture_ca_provider.client.certificate_authorities.begin_delete.return_value = mock_poller(sentinel)

    result = fixture_ca_provider.delete(
        certificate_authority_name="ca", namespace_name="ns", resource_group_name="rg",
    )

    assert result == sentinel
    fixture_ca_provider.client.certificate_authorities.begin_delete.assert_called_once_with(
        resource_group_name="rg", namespace_name="ns", certificate_authority_name="ca",
    )


# ==================== Activate ====================


def test_activate_ca(fixture_ca_provider, mock_poller, ca_pki):
    """Activate triggers begin_activate with the certificate chain body."""
    sentinel = Mock()
    chain = ca_pki["chain"]
    fixture_ca_provider.client.certificate_authorities.get.return_value = ca_pki["resource"]
    fixture_ca_provider.client.certificate_authorities.begin_activate.return_value = mock_poller(sentinel)

    result = fixture_ca_provider.activate(
        certificate_authority_name="ca", namespace_name="ns", resource_group_name="rg",
        certificate_chain=chain,
    )

    assert result == fixture_ca_provider.client.certificate_authorities.get.return_value
    assert fixture_ca_provider.client.certificate_authorities.get.call_count == 2
    fixture_ca_provider.client.certificate_authorities.begin_activate.assert_called_once_with(
        resource_group_name="rg", namespace_name="ns", certificate_authority_name="ca",
        body={"certificateChain": chain},
    )


# ==================== Revoke ====================


def test_revoke_ca(fixture_ca_provider, mock_poller):
    """Revoke triggers the begin_revoke_and_rotate LRO and returns the result."""
    sentinel = Mock()
    fixture_ca_provider.client.certificate_authorities.get.return_value = {
        "properties": {
            "certificateAuthorityType": "ICA",
            "issuer": {"issuerType": "Microsoft"},
        }
    }
    fixture_ca_provider.client.certificate_authorities.begin_revoke_and_rotate.return_value = mock_poller(sentinel)

    result = fixture_ca_provider.revoke(
        certificate_authority_name="ca", namespace_name="ns", resource_group_name="rg",
    )

    assert result == fixture_ca_provider.client.certificate_authorities.get.return_value
    assert fixture_ca_provider.client.certificate_authorities.get.call_count == 2
    fixture_ca_provider.client.certificate_authorities.begin_revoke_and_rotate.assert_called_once_with(
        resource_group_name="rg", namespace_name="ns", certificate_authority_name="ca",
    )


def test_activate_rejects_internal_ica(fixture_ca_provider):
    fixture_ca_provider.client.certificate_authorities.get.return_value = {
        "properties": {
            "certificateAuthorityType": "ICA",
            "issuer": {"issuerType": "Internal"},
        }
    }

    with pytest.raises(ArgumentUsageError, match="issuerType 'External'"):
        fixture_ca_provider.activate(
            certificate_authority_name="ca",
            namespace_name="ns",
            resource_group_name="rg",
            certificate_chain="chain",
        )
    fixture_ca_provider.client.certificate_authorities.begin_activate.assert_not_called()


def test_revoke_rejects_external_ica(fixture_ca_provider):
    fixture_ca_provider.client.certificate_authorities.get.return_value = {
        "properties": {
            "certificateAuthorityType": "ICA",
            "issuer": {"issuerType": "External"},
        }
    }

    with pytest.raises(ArgumentUsageError, match="issuerType 'Microsoft'"):
        fixture_ca_provider.revoke(
            certificate_authority_name="ca",
            namespace_name="ns",
            resource_group_name="rg",
        )
    fixture_ca_provider.client.certificate_authorities.begin_revoke_and_rotate.assert_not_called()


# ==================== --no-wait + guards ====================


def test_create_ca_no_wait_returns_poller(fixture_ca_provider, mock_poller):
    """With --no-wait, create returns the poller without waiting."""
    poller = mock_poller({"name": "ca"})
    fixture_ca_provider.client.certificate_authorities.begin_create_or_replace.return_value = poller
    fixture_ca_provider.client.namespaces.get.return_value = {"location": "eastus"}

    result = fixture_ca_provider.create(
        certificate_authority_name="ca", namespace_name="ns", resource_group_name="rg",
        certificate_authority_type="Root", no_wait=True,
    )

    assert result is poller
    poller.result.assert_not_called()


def test_delete_ca_no_wait_returns_poller(fixture_ca_provider, mock_poller):
    """With --no-wait, delete returns the poller without waiting."""
    poller = mock_poller(None)
    fixture_ca_provider.client.certificate_authorities.begin_delete.return_value = poller

    result = fixture_ca_provider.delete(
        certificate_authority_name="ca", namespace_name="ns", resource_group_name="rg", no_wait=True,
    )

    assert result is poller
    poller.result.assert_not_called()


def test_update_ca_requires_a_field(fixture_ca_provider):
    """Update with no updatable fields raises RequiredArgumentMissingError."""
    with pytest.raises(RequiredArgumentMissingError):
        fixture_ca_provider.update(
            certificate_authority_name="ca", namespace_name="ns", resource_group_name="rg",
        )


def test_update_ca_no_wait_returns_poller(fixture_ca_provider, mock_poller):
    """With --no-wait, update returns the poller without waiting or re-fetching."""
    poller = mock_poller(Mock())
    fixture_ca_provider.client.certificate_authorities.begin_update.return_value = poller

    result = fixture_ca_provider.update(
        certificate_authority_name="ca", namespace_name="ns", resource_group_name="rg",
        tags={"env": "prod"}, no_wait=True,
    )

    assert result is poller
    poller.result.assert_not_called()
    fixture_ca_provider.client.certificate_authorities.get.assert_not_called()


@pytest.mark.parametrize("days,seconds,warns", [(365, -1, True), (365, 0, True), (365, 1, False), (730, 0, False)])
def test_preflight_remaining_margin(days, seconds, warns, caplog):
    from datetime import timedelta
    from azext_iot.adr.providers.certificate_helpers import validate_external_certificate_chain
    from azext_iot.tests.adr._certificate_fixtures import NOW, certificate_fixture

    pki = certificate_fixture(remaining=timedelta(days=days, seconds=seconds))
    validate_external_certificate_chain(pki["chain"], pki["resource"], now=NOW)
    assert ("365 days" in caplog.text) == warns


@pytest.mark.parametrize("defect", ["expired", "mismatch", "reversed", "malformed", "trailing", "empty", "multiple"])
def test_preflight_deterministic_defects(defect, fixture_ca_provider, ca_pki):
    from datetime import timedelta
    from azure.cli.core.azclierror import InvalidArgumentValueError
    from azext_iot.tests.adr._certificate_fixtures import certificate_fixture

    pki = certificate_fixture(
        remaining=timedelta(seconds=-1) if defect in ("expired", "multiple") else timedelta(days=730),
        mismatch=defect in ("mismatch", "multiple"),
    )
    chain = pki["chain"]
    expected = {"expired": "expired", "mismatch": "does not match", "reversed": "verified issuer",
                "malformed": "malformed", "trailing": "only PEM", "empty": "only PEM", "multiple": "expired"}[defect]
    if defect == "reversed":
        chain = pki["root"] + pki["leaf"]
    elif defect == "malformed":
        chain += "-----BEGIN CERTIFICATE-----\nbroken\n-----END CERTIFICATE-----"
    elif defect == "trailing":
        chain += "not a certificate"
    elif defect == "empty":
        chain = ""
    fixture_ca_provider.client.certificate_authorities.get.return_value = pki["resource"]
    with pytest.raises(InvalidArgumentValueError, match=expected) as raised:
        fixture_ca_provider.activate("ca", "ns", "rg", chain, no_wait=True)
    if defect == "multiple":
        assert "does not match" in str(raised.value)
    fixture_ca_provider.client.certificate_authorities.begin_activate.assert_not_called()
    assert fixture_ca_provider.client.certificate_authorities.get.call_count == 1


@pytest.mark.parametrize("defect", ["future", "missing-extension", "no-csr", "bad-csr", "extra-eku"])
def test_preflight_uncertain_findings_warn_without_rewriting(defect, caplog):
    from datetime import timedelta
    from azext_iot.adr.providers.certificate_helpers import validate_external_certificate_chain
    from azext_iot.tests.adr._certificate_fixtures import NOW, certificate_fixture

    pki = certificate_fixture(starts=timedelta(days=1 if defect == "future" else -1),
                              copy_extensions=defect != "missing-extension", extra_eku=defect == "extra-eku")
    if defect in ("no-csr", "bad-csr"):
        pki["resource"]["properties"]["issuer"]["certificateSigningRequest"] = None if defect == "no-csr" else "bad"
    chain = " \n" + pki["chain"].replace("\n", "\r\n") + "\t"
    validate_external_certificate_chain(chain, pki["resource"], now=NOW)
    expected = {"future": "not yet valid", "missing-extension": "missing requested",
                "no-csr": "not verified", "bad-csr": "not verified"}
    if defect in expected:
        assert expected[defect] in caplog.text
    else:
        assert not caplog.text


@pytest.mark.parametrize("message,hint", [
    ("(CertificateExpiringSoon) too short", "remaining certificate validity"),
    ("InvalidPropertyValue properties.certificateProperties.extendedKeyUsage requires at least one value", "extended key usage"),
    ("InvalidCertificateChain invalid chain", None),
    ("AuthorizationFailed", None),
    ("InvalidPropertyValue properties.certificateProperties.extendedKeyUsage unknown", None),
])
def test_activation_service_hints_are_narrow(message, hint, caplog):
    from azure.core.exceptions import HttpResponseError
    from azext_iot.adr.providers.certificate_helpers import log_activation_error_hint

    error = HttpResponseError(message)
    log_activation_error_hint(error)
    assert str(error) == message
    if hint:
        assert hint in caplog.text
        assert len(caplog.records) == 1
    else:
        assert not caplog.records


def test_chain_order_requires_verified_signature():
    from azext_iot.adr.providers.certificate_helpers import validate_external_certificate_chain
    from azext_iot.tests.adr._certificate_fixtures import NOW, certificate_fixture

    pki = certificate_fixture()
    unrelated = certificate_fixture()
    # Same issuer name is insufficient to prove a chain relationship.
    validate_external_certificate_chain(pki["leaf"] + unrelated["root"], pki["resource"], now=NOW)


def test_chain_order_does_not_reject_ambiguous_issuers():
    from azext_iot.adr.providers.certificate_helpers import validate_external_certificate_chain
    from azext_iot.tests.adr._certificate_fixtures import NOW, certificate_fixture

    pki = certificate_fixture()
    validate_external_certificate_chain(pki["root"] + pki["leaf"] + pki["root"], {}, now=NOW)


@pytest.mark.parametrize("expired", [False, True])
def test_unsupported_csr_key_warns_and_preserves_other_findings(expired, caplog):
    import base64
    from datetime import timedelta
    from cryptography import x509
    from cryptography.exceptions import UnsupportedAlgorithm
    from cryptography.hazmat.primitives.serialization import Encoding
    from azure.cli.core.azclierror import InvalidArgumentValueError
    from azext_iot.adr.providers.certificate_helpers import validate_external_certificate_chain
    from azext_iot.tests.adr._certificate_fixtures import NOW, certificate_fixture

    pki = certificate_fixture(remaining=timedelta(seconds=-1) if expired else timedelta(days=730))
    issuer = pki["resource"]["properties"]["issuer"]
    csr = x509.load_pem_x509_csr(issuer["certificateSigningRequest"].encode())
    algorithm = bytes.fromhex("06072a8648ce3d0201")
    der = csr.public_bytes(Encoding.DER)
    assert der.count(algorithm) == 1
    der = der.replace(algorithm, bytes.fromhex("06072a8648ce3d027f"))
    issuer["certificateSigningRequest"] = (
        "-----BEGIN CERTIFICATE REQUEST-----\n" + base64.b64encode(der).decode()
        + "\n-----END CERTIFICATE REQUEST-----\n"
    )
    unsupported = x509.load_pem_x509_csr(issuer["certificateSigningRequest"].encode())
    with pytest.raises(UnsupportedAlgorithm):
        unsupported.public_key()
    if expired:
        with pytest.raises(InvalidArgumentValueError, match="expired"):
            validate_external_certificate_chain(pki["chain"], pki["resource"], now=NOW)
    else:
        validate_external_certificate_chain(pki["chain"], pki["resource"], now=NOW)
    assert "public-key match and requested extensions were not verified" in caplog.text


@pytest.mark.parametrize("unsupported", [False, True])
def test_certificate_key_failure_is_distinguished_from_unreadable_csr(unsupported, monkeypatch, caplog):
    from cryptography import x509
    from cryptography.exceptions import UnsupportedAlgorithm
    from azure.cli.core.azclierror import InvalidArgumentValueError
    from azext_iot.adr.providers import certificate_helpers as helpers
    from azext_iot.tests.adr._certificate_fixtures import NOW, certificate_fixture

    pki = certificate_fixture(copy_extensions=False)
    original = helpers._public_key_bytes

    def public_key(certificate):
        if isinstance(certificate, x509.Certificate):
            raise UnsupportedAlgorithm("unsupported key") if unsupported else ValueError("malformed key")
        return original(certificate)

    monkeypatch.setattr(helpers, "_public_key_bytes", public_key)
    if unsupported:
        helpers.validate_external_certificate_chain(pki["chain"], pki["resource"], now=NOW)
        assert "unsupported locally; public-key match was not verified" in caplog.text
    else:
        with pytest.raises(InvalidArgumentValueError, match="certificate public key is malformed"):
            helpers.validate_external_certificate_chain(pki["chain"], pki["resource"], now=NOW)
    assert "missing requested CSR extensions" in caplog.text


def test_self_issued_rollover_requires_leaf_to_verified_root_order():
    from datetime import timedelta
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding
    from cryptography.x509.oid import NameOID
    from azure.cli.core.azclierror import InvalidArgumentValueError
    from azext_iot.adr.providers.certificate_helpers import validate_external_certificate_chain
    from azext_iot.tests.adr._certificate_fixtures import NOW

    root_key, rollover_key, leaf_key = [ec.generate_private_key(ec.SECP384R1()) for _ in range(3)]
    root_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Rollover authority")])
    leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Service ICA")])

    def issue(subject, issuer, key, signer):
        return (
            x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(NOW - timedelta(days=1))
            .not_valid_after(NOW + timedelta(days=730)).sign(signer, hashes.SHA384())
        )

    root = issue(root_name, root_name, root_key, root_key)
    rollover = issue(root_name, root_name, rollover_key, root_key)
    leaf = issue(leaf_name, root_name, leaf_key, rollover_key)
    csr = x509.CertificateSigningRequestBuilder().subject_name(leaf_name).sign(leaf_key, hashes.SHA384())
    resource = {"properties": {"issuer": {"certificateSigningRequest": csr.public_bytes(Encoding.PEM).decode()}}}
    invalid = b"".join(cert.public_bytes(Encoding.PEM) for cert in (leaf, root, rollover)).decode()
    with pytest.raises(InvalidArgumentValueError, match="Certificate 3 follows its verified issuer 2"):
        validate_external_certificate_chain(invalid, resource, now=NOW)
    valid = b"".join(cert.public_bytes(Encoding.PEM) for cert in (leaf, rollover, root)).decode()
    validate_external_certificate_chain(valid, resource, now=NOW)


@pytest.mark.parametrize("value", ["", "false", "0"])
@pytest.mark.parametrize("no_wait", [False, True])
def test_live_revocation_gate_precedes_all_resource_work(value, no_wait, monkeypatch, mocker):
    from azext_iot.tests.adr.test_adr_certificate_authority_int import TestADRCAActions

    monkeypatch.setenv("azext_iot_adr_revoke_certificates", value)
    scenario = TestADRCAActions("test_microsoft_revocation")
    owned = mocker.patch.object(scenario, "_owned_target")
    with pytest.raises(pytest.skip.Exception, match="explicit"):
        scenario._microsoft_revocation(no_wait=no_wait)
    owned.assert_not_called()


@pytest.fixture
def signing_directory(tmp_path):
    from pathlib import Path
    from tempfile import TemporaryDirectory

    with TemporaryDirectory(dir=tmp_path, prefix="private-pki-") as directory:
        yield Path(directory)


def test_documented_openssl_signer_preserves_service_csr_key(signing_directory, ca_pki):
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from azext_iot.tests.adr.test_adr_certificate_authority_int import TestADRCAActions

    path = TestADRCAActions._sign_service_csr(signing_directory, ca_pki["resource"])
    leaf = x509.load_pem_x509_certificate(path.read_bytes())
    csr = x509.load_pem_x509_csr(
        ca_pki["resource"]["properties"]["issuer"]["certificateSigningRequest"].encode(),
    )
    assert leaf.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo) == (
        csr.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    )
    for extension in csr.extensions:
        assert leaf.extensions.get_extension_for_oid(extension.oid) == extension
    assert (signing_directory / "root.key").stat().st_mode & 0o777 == 0o600
    root = x509.load_pem_x509_certificate((signing_directory / "root.pem").read_bytes())
    assert root.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    assert root.extensions.get_extension_for_class(x509.KeyUsage).value.key_cert_sign
    assert root.not_valid_after_utc >= leaf.not_valid_after_utc
    leaf.verify_directly_issued_by(root)


def test_external_ca_help_recipe_and_output_contract():
    from knack.help_files import helps
    from azext_iot.adr._help import load_adr_help

    load_adr_help()
    activation = helps["iot adr ns ca activate"]
    for text in ("properties.issuer.certificateSigningRequest", "-copy_extensions copy", "umask 077",
                 "leaf to root", "730 days is illustrative", "not a universal", "--no-wait"):
        assert text in activation
    assert "does not prove" in helps["iot adr ns ca revoke"]


def test_live_no_wait_revoke_opt_in_reaches_owned_provisioning(monkeypatch, mocker):
    from azext_iot.tests.adr.test_adr_certificate_authority_int import TestADRCAActions

    monkeypatch.setenv("azext_iot_adr_revoke_certificates", "true")
    scenario = TestADRCAActions("test_microsoft_revocation_no_wait")
    owned = mocker.patch.object(scenario, "_owned_target", side_effect=CLIError("owned provisioning reached"))
    with pytest.raises(CLIError, match="owned provisioning reached"):
        scenario._microsoft_revocation(no_wait=True)
    owned.assert_called_once_with(microsoft=True)


@pytest.mark.parametrize("stage", ["namespace", "root", "ica", "scenario"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_live_owned_ca_partial_allocation_and_cleanup(stage, cleanup_fails, mocker, caplog):
    from azext_iot.tests.adr import test_adr_certificate_authority_int as live

    scenario = live.TestADRCAActions("test_microsoft_revocation")
    mocker.patch.object(live, "generate_adr_namespace_name", return_value="owned")
    mocker.patch.object(scenario, "_ready")
    created = []
    deleted = []

    def absent(_test, command):
        name = "namespace" if command.startswith("iot adr ns show") else ("root" if "-n root " in command else "ica")
        return name not in created

    mocker.patch.object(live, "resource_is_absent", side_effect=absent)
    mocker.patch.object(live, "wait_for_resource_absent")

    def invoke(command):
        name = "namespace" if command.startswith("iot adr ns create") or command.startswith("iot adr ns delete") else (
            "root" if "-n root " in command else "ica"
        )
        if " create " in command:
            created.append(name)
            if stage == name:
                raise CLIError("primary allocation error")
        if " delete " in command:
            deleted.append(name)
            if cleanup_fails:
                raise CLIError("cleanup timeout")
        return Mock(get_output_in_json=Mock(return_value={"id": "owned-ica"}))

    mocker.patch.object(scenario, "cmd", side_effect=invoke)
    with pytest.raises(CLIError, match="primary"):
        with scenario._owned_target(microsoft=True):
            raise CLIError("primary scenario error")
    assert deleted == ([created[-1]] if cleanup_fails else list(reversed(created)))
    if cleanup_fails:
        assert "cleanup timeout" in caplog.text
        assert "/namespaces/owned" in caplog.text
        if len(created) > 1:
            assert "Dependent cleanup has not completed" in caplog.text


def test_live_collision_never_deletes_borrowed_ca(mocker):
    from azext_iot.tests.adr import test_adr_certificate_authority_int as live

    scenario = live.TestADRCAActions("test_external_activation_recipe")
    mocker.patch.object(live, "resource_is_absent", return_value=False)
    command = mocker.patch.object(scenario, "cmd")
    with pytest.raises(AssertionError, match="Refusing to overwrite"):
        with scenario._owned_target():
            pytest.fail("A borrowed namespace was admitted")
    command.assert_not_called()


@pytest.mark.parametrize("signer_fails", [False, True])
def test_live_private_key_directory_removed_after_failure(signer_fails, ca_pki, mocker):
    from contextlib import contextmanager
    from pathlib import Path
    from subprocess import CalledProcessError
    from azext_iot.tests.adr import test_adr_certificate_authority_int as live

    scenario = live.TestADRCAActions("test_external_activation_no_wait")

    @contextmanager
    def owned():
        resource_id = (
            f"/subscriptions/{live.TEST_SUBSCRIPTION}/resourceGroups/{live.TEST_RG}"
            "/providers/Microsoft.DeviceRegistry/namespaces/owned/certificateAuthorities/ica"
        )
        scenario._owned_ca_ids = {resource_id}
        scenario._ca_actions = {}
        yield "--ns owned -g rg", dict(ca_pki["resource"], id=resource_id)

    mocker.patch.object(scenario, "_owned_target", owned)
    run = live.subprocess.run
    private_keys = []

    def signing(command, **kwargs):
        if "-keyout" in command:
            key = Path(command[command.index("-keyout") + 1])
            private_keys.append(key)
            assert key.stat().st_mode & 0o777 == 0o600
        if signer_fails:
            raise CalledProcessError(1, command, stderr="signing failed")
        return run(command, check=kwargs.pop("check"), **kwargs)

    mocker.patch.object(live.subprocess, "run", side_effect=signing)
    mocker.patch.object(scenario, "cmd", side_effect=CLIError("activation failed"))
    with pytest.raises(CalledProcessError if signer_fails else CLIError):
        scenario._external_activation(no_wait=True)
    assert private_keys
    assert all(not key.parent.exists() for key in private_keys)


def test_live_read_deadline_includes_service_call_time(mocker):
    from azext_iot.tests.adr import test_adr_certificate_authority_int as live

    mocker.patch.object(live, "monotonic", side_effect=[0, 601])
    with pytest.raises(AssertionError, match="Timed out reading"):
        live.TestADRCAActions._bounded_read(lambda: {"properties": {}}, lambda _value: True, "CA")


def test_live_cleanup_only_failure_reports_exact_owned_residuals(mocker):
    from azext_iot.tests.adr import test_adr_certificate_authority_int as live

    scenario = live.TestADRCAActions("test_external_activation_recipe")
    mocker.patch.object(live, "generate_adr_namespace_name", return_value="owned")
    mocker.patch.object(live, "resource_is_absent", side_effect=[True, True, False])
    mocker.patch.object(scenario, "_ready")

    def invoke(command):
        if " delete " in command:
            raise CLIError("cleanup rejected")
        return Mock(get_output_in_json=Mock(return_value={"id": "owned-ica"}))

    mocker.patch.object(scenario, "cmd", side_effect=invoke)
    with pytest.raises(AssertionError, match="ADR cleanup failed") as raised:
        with scenario._owned_target():
            pass
    assert "/namespaces/owned/certificateAuthorities/ica: cleanup rejected" in str(raised.value)
    assert "/namespaces/owned: Dependent cleanup has not completed" in str(raised.value)


@pytest.mark.parametrize("issuer", [
    {"issuerType": "Microsoft"},
    {"issuerType": "Microsoft", "futureField": "from-service"},
    {"issuerType": "External", "status": "Active", "thumbprint": "service-thumbprint"},
])
def test_live_raw_comparison_preserves_service_issuer_fields(issuer, mocker):
    from azext_iot.tests.adr import test_adr_certificate_authority_int as live

    scenario = live.TestADRCAActions("test_external_activation_recipe")
    resource = {"id": "/subscriptions/owned/namespaces/ns/certificateAuthorities/ica", "properties": {"issuer": issuer}}
    command = mocker.patch.object(scenario, "cmd", return_value=Mock(
        get_output_in_json=Mock(return_value=resource),
    ))
    scenario._assert_raw_fields(resource)
    assert command.call_count == 1
    assert "rest --method get" in command.call_args.args[0]
    assert f"?api-version={live.TEST_API_VERSION}" in command.call_args.args[0]
