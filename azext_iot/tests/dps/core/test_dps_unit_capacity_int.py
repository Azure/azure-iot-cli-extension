# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Owned, sequential DPS-only capacity qualification; never submit live capacity above one."""

from contextlib import ExitStack, contextmanager
from time import time
from unittest.mock import patch
from urllib.parse import urlsplit

import pytest
from azure.cli.core.azclierror import InvalidArgumentValueError
from azure.core.pipeline.transport import RequestsTransport

from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.dps import _phase, _phase_receipts, _phase_runtime
from azext_iot.tests.dps import conftest as fixtures
from azext_iot.tests.helpers import invoke_checked


@contextmanager
def _observe_management_requests():
    original = RequestsTransport.send
    observed = []

    def send(transport, request, **kwargs):
        observed.append((request.method, urlsplit(request.url).path))
        return original(transport, request, **kwargs)

    with patch.object(RequestsTransport, "send", send):
        yield observed


def test_dps_unit_capacity_owned_lifecycle(request):
    if not _phase_receipts.settings() or _phase.get_phase() != _phase.REGULAR:
        raise pytest.UsageError("DPS capacity qualification requires the admitted, receipt-enabled regular DPS runner.")
    cli = EmbeddedCLI()
    run_uid = fixtures._get_run_uid(request)
    group = fixtures.ENTITY_RG
    # Two existing shared fixtures plus this sequential allocation are admitted
    # by the runner, including an unexpected create if negative validation regresses.
    for kind, invalid, unit_option in (("unit1", 0, "--unit 1"), ("unitdefault", -1, "")):
        name = f"clitest-dps-{kind}-{run_uid[:12]}"
        target = f"--name {name} --resource-group {group}"
        tags = f"intTest=true runUid={run_uid} kind={kind} createdEpoch={int(time())}"
        create = f"iot dps create {target} --location {fixtures.ENTITY_LOCATION} --tags {tags}"
        assert fixtures._find_dps_by_name(name) is None
        with ExitStack() as cleanup:
            _phase_receipts.before_create(name, group, run_uid, kind)
            cleanup.callback(
                fixtures._cleanup_created_resource, name, run_uid, kind,
                fixtures._find_dps_by_name, fixtures._delete_dps,
            )
            with _phase_runtime.owned_write(name, "PUT"), _observe_management_requests() as observed:
                with pytest.raises(InvalidArgumentValueError, match="--unit.*greater than or equal to 1"):
                    invoke_checked(cli, f"{create} --unit {invalid}", description="Invalid owned DPS units")
            assert not cli.output.strip()
            assert not observed
            assert fixtures._find_dps_by_name(name) is None

            # Reuse the proven-absent owned name for its positive control. This
            # resolves the same pre-create receipt without inventing a creation.
            with _phase_runtime.owned_write(name, "PUT"):
                created = invoke_checked(cli, f"{create} {unit_option}", description="Owned DPS unit control").as_json()
            _phase_receipts.after_create(name, created)
            actual = fixtures._find_dps_by_name(name)
            assert actual["id"] == created["id"]
            assert created["sku"]["capacity"] == actual["sku"]["capacity"] == 1
            assert actual["properties"]["provisioningState"].lower() == "succeeded"
            assert actual["properties"]["disableLocalAuth"] is True
            assert any(item["id"] == actual["id"] for item in invoke_checked(
                cli, f"iot dps list -g {group}", description="Owned DPS list inclusion",
            ).as_json())

            if kind == "unit1":
                for capacity in (0, -1):
                    with _observe_management_requests() as observed:
                        with pytest.raises(InvalidArgumentValueError, match="sku.capacity.*greater than or equal to 1"):
                            invoke_checked(
                                cli, f"iot dps update {target} --set sku.capacity={capacity}",
                                description="Invalid owned DPS capacity update",
                            )
                    assert observed and all(method == "GET" for method, _ in observed)
                    unchanged = fixtures._find_dps_by_name(name)
                    assert unchanged["sku"] == actual["sku"] and unchanged["tags"] == actual["tags"]
                updated = invoke_checked(
                    cli, f"iot dps update {target} --set tags.unitValidation=passed",
                    description="Unrelated owned DPS update",
                ).as_json()
                assert updated["sku"]["capacity"] == 1 and updated["tags"]["unitValidation"] == "passed"
        assert fixtures._find_dps_by_name(name) is None
