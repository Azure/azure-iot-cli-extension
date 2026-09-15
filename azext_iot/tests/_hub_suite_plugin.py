# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Load explicitly with -p azext_iot.tests._hub_suite_plugin in each fresh phase.

Required environment: AZEXT_IOT_HUB_SUITE, AZEXT_IOT_HUB_PHASE,
AZEXT_IOT_HUB_RECEIPT (new path), AZEXT_IOT_HUB_RUN_ID (controller nonce).
Optional AZEXT_IOT_HUB_LINKED_METADATA=1 admits the separate metadata phase.
Selection must already be exact node args before initial conftest import. This
plugin validates those args early; collection_modifyitems is only a guard.
Receipts attest pytest teardown, NOT Azure resource absence. Controllers must
also require the owned resource cleanup receipts (including existing HubSAS).
"""

import json
import os
from collections import Counter
from pathlib import Path

import pytest

from azext_iot.tests import _hub_suite_manifest as manifest


def result_errors(expected, collected, reports, exitstatus, finished):
    """Pure fail-closed gate, usable by a parent reading the JSON receipt."""
    errors = []
    if not finished or exitstatus != 0:
        errors.append("phase incomplete or pytest failed")
    if (not expected or len(set(expected)) != len(expected)
            or Counter(collected) != Counter(expected) or list(collected) != list(expected)
            or len(set(collected)) != len(collected)):
        errors.append("missing, unexpected or duplicate collected nodes")
    if set(reports) != set(expected):
        errors.append("missing or unexpected reported nodes")
    for node in expected:
        stages = reports.get(node, {})
        if set(stages) != {"setup", "call", "teardown"} or any(
            stages.get(stage) != ["passed"] for stage in ("setup", "call", "teardown")
        ):
            errors.append("required node did not pass exactly once with successful teardown: " + node)
    return errors


def validate_args(config, expected, *, early=False):
    """Reject broad/filtering/parallel invocations before integration imports."""
    arguments = config.known_args_namespace.file_or_dir if early else config.args

    def option(name, default=None):
        return getattr(config.known_args_namespace, name, default) if early else config.getoption(name, default=default)

    if tuple(arg.removeprefix("./") for arg in arguments) != expected:
        raise pytest.UsageError("Hub phases require exact ordered manifest node arguments before collection.")
    if any(option(name) for name in (
        "keyword", "markexpr", "deselect", "reruns", "lf", "ff", "stepwise",
    )) or option("numprocesses") not in (None, 0):
        raise pytest.UsageError("Hub receipt phases require serial, unfiltered execution without reruns.")
    if option("collectonly", False):
        raise pytest.UsageError("Collection-only is not phase qualification; use guarded offline inventory tests.")


@pytest.hookimpl(tryfirst=True)
def pytest_load_initial_conftests(early_config, parser, args):
    suite, phase = os.getenv("AZEXT_IOT_HUB_SUITE"), os.getenv("AZEXT_IOT_HUB_PHASE")
    if not suite or not phase:
        raise pytest.UsageError("Hub selection plugin requires explicit suite and phase.")
    try:
        expected = manifest.nodes(
            suite, phase, linked_metadata=os.getenv("AZEXT_IOT_HUB_LINKED_METADATA") == "1",
        )
    except ValueError as error:
        raise pytest.UsageError(str(error)) from error
    validate_args(early_config, expected, early=True)
    auth_phase = os.getenv("azext_iot_hub_auth_phase", "regular")
    if auth_phase != ("local-auth" if phase == "sas" else "regular"):
        raise pytest.UsageError("Hub selection/auth phase mismatch; use a fresh process for each phase.")
    receipt, run_id = os.getenv("AZEXT_IOT_HUB_RECEIPT"), os.getenv("AZEXT_IOT_HUB_RUN_ID")
    if not receipt or not run_id:
        raise pytest.UsageError("Hub phase requires a new receipt path and controller run ID.")
    runtime = PhaseReceipt(suite, phase, expected, Path(receipt), run_id)
    early_config.pluginmanager.register(runtime, "hub-suite-receipt")
    ownership_path = os.getenv("AZEXT_IOT_HUB_OWNERSHIP")
    if ownership_path:
        from azext_iot.tests._dps_phase_runner import require_linux
        from azext_iot.tests._hub_ownership import ProcessScope
        require_linux()
        runtime.scope = ProcessScope()
        runtime.scope.install()
        early_config.add_cleanup(runtime.scope.restore)
    if ownership_path and phase != "sas":
        from azext_iot.tests._hub_ownership import Arm, Observer
        runtime.observer = Observer(ownership_path, run_id, phase, Arm())
        runtime.observer.install()
        early_config.add_cleanup(runtime.observer.restore)


class PhaseReceipt:
    """Record only credential-free node identities and outcomes, never tracebacks."""

    def __init__(self, suite, phase, expected, path, run_id):
        self.path = path
        self.data = {
            "schemaVersion": 1, "suite": suite, "phase": phase, "runId": run_id,
            "expected": list(expected), "collected": [], "reports": {},
            "finished": False, "exitstatus": None, "errors": ["phase incomplete"],
            "cleanup": {"pytestTeardown": "incomplete", "resourceAbsence": "not-attested"},
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive reservation: never reuse a stale successful receipt.
        with path.open("x", encoding="utf-8") as stream:
            json.dump(self.data, stream)

    def write(self):
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def pytest_configure(self, config):
        config.addinivalue_line("markers", "hub_selection: explicit Hub suite selection metadata")
        validate_args(config, tuple(self.data["expected"]))

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, session, config, items):
        self.data["collected"] = [item.nodeid for item in items]
        self.write()
        if self.data["collected"] != self.data["expected"]:
            raise pytest.UsageError("Hub phase expanded membership/order differs from the manifest.")
        metadata = {case.node: case for case in manifest.contract()}
        for item in items:
            case = metadata[item.nodeid]
            item.add_marker(pytest.mark.hub_selection(
                suite=case.suite, group=case.group, protocol=case.protocol,
                auth=case.auth, dependencies=case.dependencies, phase=self.data["phase"],
            ))

    def pytest_runtest_logreport(self, report):
        stages = self.data["reports"].setdefault(report.nodeid, {})
        outcome = "xfail" if hasattr(report, "wasxfail") else report.outcome
        stages.setdefault(report.when, []).append(outcome)
        self.write()

    def pytest_runtest_logstart(self, nodeid, location):
        if getattr(self, "observer", None):
            self.observer.current_node = nodeid

    def pytest_runtest_logfinish(self, nodeid, location):
        if getattr(self, "observer", None):
            self.observer.current_node = None

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_sessionfinish(self, session, exitstatus):
        # Outermost wrapper: account for failures/cleanup in other finish hooks.
        outcome = yield
        self.data["finished"] = outcome.excinfo is None
        self.data["exitstatus"] = int(session.exitstatus)
        self.data["errors"] = result_errors(
            self.data["expected"], self.data["collected"], self.data["reports"],
            self.data["exitstatus"], self.data["finished"],
        )
        teardown_ok = all(
            self.data["reports"].get(node, {}).get("teardown") == ["passed"] for node in self.data["expected"]
        )
        self.data["cleanup"]["pytestTeardown"] = "passed" if teardown_ok else "incomplete-or-failed"
        if self.data["errors"] and session.exitstatus == 0:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
            self.data["exitstatus"] = int(session.exitstatus)
        self.write()
