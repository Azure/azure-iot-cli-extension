# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Surviving GitHub workflow contracts and shared integration runtime budgets."""

import json
from pathlib import Path
import re

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
SERVICES = ("DPS", "HubControl", "HubData", "ADU", "ADR")


@pytest.mark.parametrize("retired", [
    "int_test.yml", "release_workflow.yml", "trigger_ado_int_tests.yml", "int_test_schedule.yml",
])
def test_retired_live_and_release_entrypoints_have_no_remaining_github_callers(retired):
    workflows = ROOT / ".github/workflows"
    assert not (workflows / retired).exists()
    for path in workflows.glob("*.y*ml"):
        assert retired not in path.read_text(encoding="utf-8"), path.name


def _ci_budgets():
    return json.loads((ROOT / "azext_iot/tests/ci_budgets.json").read_text(encoding="utf-8"))


def test_external_actions_are_pinned_to_full_shas_with_version_comments():
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.search(r"uses:\s+([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?@([^ #]+))", line)
            if not match:
                continue
            ref = match.group(2)
            assert re.fullmatch(r"[0-9a-f]{40}", ref), f"{path.name}: {line}"
            assert re.search(r"# v\d+\.\d+\.\d+\s*$", line), f"{path.name}: {line}"


def _expression_contexts(value):
    contexts = set()
    for expression in re.findall(r"\$\{\{(.*?)\}\}", value):
        # Ignore quoted literals (including bracket-access property names), and
        # inspect root property/index access rather than nested field names.
        expression = re.sub(r"'(?:''|[^'])*'", "''", expression)
        contexts.update(re.findall(r"(?<![\w.])([A-Za-z_]\w*)\s*[.\[]", expression))
    return contexts


def test_reusable_job_with_uses_only_officially_supported_expression_contexts():
    # Official context-availability row jobs.<job_id>.with.<with_id>.
    # A schema-valid job can still be invalid if it uses secrets or env here.
    allowed = {"github", "needs", "strategy", "matrix", "inputs", "vars"}
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in workflow["jobs"].values():
            if "uses" in job:
                for name, value in job.get("with", {}).items():
                    if isinstance(value, str):
                        assert _expression_contexts(value) <= allowed, (path.name, name, value)


@pytest.mark.parametrize("context", ["secrets", "env", "steps", "job", "runner"])
@pytest.mark.parametrize("access", [".VALUE", "['VALUE']"])
def test_expression_context_check_detects_unsupported_dot_and_bracket_access(context, access):
    assert _expression_contexts("${{ inputs['subscription-id'] || " + context + access + " }}") == {
        "inputs", context,
    }


def test_ci_budget_source_covers_matrix_and_controller_arithmetic():
    budgets = _ci_budgets()
    assert set(budgets) == set(SERVICES)
    for service, config in budgets.items():
        assert config["tox_env"] == service + "-int"
        assert isinstance(config.get("concurrent_phases", False), bool)
        # Concurrent controllers run every phase at once, so only the slowest phase bounds the job.
        combine = max if config.get("concurrent_phases") else sum
        assert isinstance(config.get("serial_cleanup_verification", False), bool)
        verification = (
            sum(phase["cleanup_minutes"] for phase in config["phases"])
            if config.get("serial_cleanup_verification") else 0
        )
        controller = (
            combine([phase["runtime_minutes"] + phase["cleanup_minutes"] for phase in config["phases"]] or [0])
            + verification + config["reserve_minutes"]
        )
        assert controller + config["setup_minutes"] <= config["job_timeout_minutes"]
    assert {
        service: budgets[service]["job_timeout_minutes"] for service in ("DPS", "HubControl", "HubData", "ADU", "ADR")
    } == {"DPS": 90, "HubControl": 130, "HubData": 115, "ADU": 150, "ADR": 180}
