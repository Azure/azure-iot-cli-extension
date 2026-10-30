# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from contextlib import ExitStack
from hashlib import sha256
from shlex import quote
from time import time

import pytest

from azext_iot.common._azure import parse_iot_dps_connection_string
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.dps import _phase, _phase_receipts, _phase_runtime
from azext_iot.tests.dps import conftest as fixtures
from azext_iot.tests.helpers import invoke_checked, policy_snapshot
from azext_iot.tests.test_utils import certificate_fingerprints, create_certificate


@pytest.mark.timeout(600, func_only=False)
def test_dps_management_happy_paths(request, tmp_path):
    if not _phase_receipts.settings() or _phase.get_phase() != _phase.REGULAR:
        raise pytest.UsageError("DPS management qualification requires the admitted, receipt-enabled regular DPS runner.")
    cli = EmbeddedCLI()
    run_uid = fixtures._get_run_uid(request)
    kind = "control"
    name = f"clitest-dps-{kind}-{run_uid[:12]}"
    group = fixtures.ENTITY_RG

    def command(operation, *, output=True):
        name_option = "--name" if operation.startswith("identity ") else "--dps-name"
        result = invoke_checked(
            cli, f"iot dps {operation} {name_option} {name} -g {group}",
            description="Owned DPS management happy path",
        )
        return result.as_json() if output else None

    assert fixtures._find_dps_by_name(name) is None
    with ExitStack() as cleanup:
        _phase_receipts.before_create(name, group, run_uid, kind)
        cleanup.callback(
            fixtures._cleanup_created_resource, name, run_uid, kind,
            fixtures._find_dps_by_name, fixtures._delete_dps,
        )
        with _phase_runtime.owned_write(name, "PUT"):
            created = invoke_checked(
                cli,
                f"iot dps create -n {name} -g {group} --location {fixtures.ENTITY_LOCATION} "
                f"--disable-local-auth true --tags intTest=true runUid={run_uid} kind={kind} createdEpoch={int(time())}",
                description="Create isolated management-test DPS",
            ).as_json()
        _phase_receipts.after_create(name, created)
        assert not created["properties"].get("iotHubs")

        baseline = policy_snapshot(command("policy list"))
        policy_name = "command-happy-path"
        # DPS requires registration-read permission alongside enrollment-read.
        read_rights = ("EnrollmentRead", "RegistrationStatusRead")
        write_rights = (*read_rights, "EnrollmentWrite", "RegistrationStatusWrite")
        policy = command(f"policy create --policy-name {policy_name} --rights {' '.join(read_rights)}")
        initial = policy_snapshot([policy])
        assert initial[policy_name][0] == set(read_rights)
        assert policy_snapshot([command(f"policy show --policy-name {policy_name}")]) == initial
        assert policy_snapshot(command("policy list")) == {**baseline, **initial}

        policy = command(f"policy update --policy-name {policy_name} --rights {' '.join(write_rights)}")
        updated = policy_snapshot([policy])
        assert updated[policy_name][0] == set(write_rights)
        assert updated[policy_name][1:] == initial[policy_name][1:]
        assert policy_snapshot([command(f"policy show --policy-name {policy_name}")]) == updated
        connection = parse_iot_dps_connection_string(command(
            f"connection-string show --policy-name {policy_name} --key-type secondary",
        )["connectionString"])
        assert connection["HostName"] == created["properties"]["serviceOperationsHostName"]
        assert connection["SharedAccessKeyName"] == policy_name
        fingerprint = sha256(connection["SharedAccessKey"].encode()).hexdigest()
        assert fingerprint == updated[policy_name][2]
        command(f"policy delete --policy-name {policy_name}", output=False)
        assert policy_snapshot(command("policy list")) == baseline

        certificate_name = "command-happy-path"
        first = create_certificate("initial-root", 1, str(tmp_path))
        replacement = create_certificate("replacement-root", 1, str(tmp_path))
        first_path = quote(str(tmp_path / "initial-root-cert.pem"))
        replacement_path = quote(str(tmp_path / "replacement-root-cert.pem"))
        certificate = command(f"certificate create --certificate-name {certificate_name} --path {first_path}")
        shown = command(f"certificate show --certificate-name {certificate_name}")
        assert shown["id"] == certificate["id"]
        assert shown["properties"]["thumbprint"].upper() in certificate_fingerprints(first["certificate"])
        listed = command("certificate list")["value"]
        assert [item["id"] for item in listed if item["name"] == certificate_name] == [shown["id"]]
        updated_certificate = command(
            f"certificate update --certificate-name {certificate_name} --path {replacement_path} "
            f"--etag {quote(shown['etag'])}",
        )
        readback = command(f"certificate show --certificate-name {certificate_name}")
        assert readback["id"] == shown["id"]
        assert readback["properties"]["thumbprint"] == updated_certificate["properties"]["thumbprint"]
        assert readback["properties"]["thumbprint"].upper() in certificate_fingerprints(replacement["certificate"])
        assert readback["properties"]["thumbprint"] != shown["properties"]["thumbprint"]
        command(f"certificate delete --certificate-name {certificate_name} --etag {quote(readback['etag'])}", output=False)
        assert certificate_name not in {item["name"] for item in command("certificate list")["value"]}

        assigned = command("identity assign --system-assigned")
        identity = command("identity show")
        assert identity["type"] == "SystemAssigned"
        assert identity["principalId"] == assigned["identity"]["principalId"]
        assert identity["principalId"] and identity["tenantId"]
        command("identity remove --system-assigned", output=False)
        final = fixtures._find_dps_by_name(name)
        removed = final.get("identity")
        assert removed is None or removed.get("type") == "None"
        assert not final["properties"].get("iotHubs")
        assert final["properties"]["disableLocalAuth"] is True
        assert final["tags"] == created["tags"]
    assert fixtures._find_dps_by_name(name) is None
