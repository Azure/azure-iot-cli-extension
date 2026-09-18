# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline topology, matrix and artifact contracts for the locked integration bundle."""

from collections import Counter
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
FILES = ("int_test.yml", "int_test_bundle.yml", "int_test_cohort.yml")
SERVICES = ("DPS", "HubControl", "HubData", "ADU", "ADR")
OWNED_SERVICES = {"DPS", "HubControl", "HubData", "ADR"}
SUBSCRIPTION = "a386d5ea-ea90-441a-8263-d816368c84a1"
POSIX_WORKFLOW = pytest.mark.skipif(
    sys.platform != "linux" or not shutil.which("bash") or not shutil.which("jq"),
    reason="Executes the Ubuntu workflow's Bash/jq, without Azure or pytest collection.",
)


def _workflows():
    return [yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8")) for name in FILES]


def _triggers(workflow):
    return workflow.get("on", workflow.get(True))


def _matrix(tmp_path, **overrides):
    workflow = _workflows()[0]
    step = next(step for step in workflow["jobs"]["setup"]["steps"] if step.get("id") == "matrix")
    env = dict(
        os.environ, INPUT_SERVICES="auto", INPUT_PYTHON_VERSIONS="3.13", INPUT_REGIONS="centraluseuap",
        RESOURCE_GROUP="cli-int-test-rg", TEST_SUBSCRIPTION_ID=SUBSCRIPTION,
        GITHUB_OUTPUT=str(tmp_path / "outputs"), GITHUB_STEP_SUMMARY=str(tmp_path / "summary"),
        **{"INPUT_TEST_" + name: "false" for name in ("DPS", "HUB_CONTROL", "HUB_DATA", "ADU", "ADR")},
    )
    env.update(overrides)
    result = subprocess.run(
        ["bash", "-c", step["run"]], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30, check=False,
    )
    path = Path(env["GITHUB_OUTPUT"])
    outputs = dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines()) if path.exists() else {}
    return result, outputs


def test_scope_lock_surrounds_all_cohorts_and_parallel_services():
    public, bundle, cohort = _workflows()
    caller = public["jobs"]["int-test"]
    assert caller["needs"] == ["setup", "unit-test"]
    assert "needs.unit-test.result == 'success'" in caller["if"]
    assert caller["concurrency"] == {
        "group": "integration-live-${{ needs.setup.outputs.live-scope }}",
        "cancel-in-progress": False,
    }
    assert caller["uses"] == "./.github/workflows/int_test_bundle.yml"
    assert caller["with"]["cohorts"] == "${{ needs.setup.outputs.cohorts }}"
    assert "strategy" not in caller  # Exactly one scope-lock contender per run.
    assert set(bundle["jobs"]) == {"cohort"}
    serial = bundle["jobs"]["cohort"]
    assert serial["uses"] == "./.github/workflows/int_test_cohort.yml"
    assert serial["strategy"] == {
        "fail-fast": False, "max-parallel": 1, "matrix": {"cohort": "${{ fromJson(inputs.cohorts) }}"},
    }
    assert serial["with"]["configs"] == "${{ toJson(matrix.cohort.configs) }}"
    assert set(cohort["jobs"]) == {"service"}
    parallel = cohort["jobs"]["service"]
    assert parallel["strategy"] == {
        "fail-fast": False, "matrix": {"config": "${{ fromJson(inputs.configs) }}"},
    }
    assert "needs" not in parallel  # No DPS -> HubControl -> HubData -> ADR chain.
    for workflow in (public, bundle, cohort):
        assert "concurrency" not in workflow
        for job in workflow["jobs"].values():
            if job is not caller:
                assert "concurrency" not in job  # No pending sibling cancellation or nested lock deadlock.
            assert not job.get("continue-on-error", False)
    for job in (serial, parallel):
        assert "if" not in job  # A failed service/cohort must not suppress the others.


def test_internal_calls_use_supported_keywords_and_forward_typed_inputs_and_oidc():
    # GitHub's "Supported keywords for jobs that call a reusable workflow".
    # In particular these calls cannot have runs-on, env, steps or timeout-minutes.
    supported = {"name", "uses", "with", "secrets", "strategy", "needs", "if", "concurrency", "permissions"}
    public, bundle, cohort = _workflows()
    callers = (public["jobs"]["int-test"], bundle["jobs"]["cohort"])
    for caller, callee in zip(callers, (bundle, cohort)):
        assert set(caller) <= supported
        assert caller["secrets"] == "inherit"
        triggers = _triggers(callee)
        assert set(triggers) == {"workflow_call"}  # Internal only; no new public dispatch/suites.
        declared = triggers["workflow_call"]["inputs"]
        assert set(caller["with"]) == set(declared)
        assert declared["adr-test-filter"]["type"] == "string"
        assert declared["adr-test-filter"]["default"] == ""
        assert declared["adr-revoke-certificates"]["type"] == "boolean"
        assert declared["adr-revoke-certificates"]["default"] is False
        assert declared["resource-group"] == {"type": "string", "required": True}
        assert declared["subscription-id"] == {"type": "string", "required": False, "default": ""}
        assert declared["dps-capacity-limit"] == {"type": "string", "required": False, "default": "10"}
        assert "inputs['adr-test-filter']" in caller["with"]["adr-test-filter"]
        assert "inputs['adr-revoke-certificates']" in caller["with"]["adr-revoke-certificates"]
        assert triggers["workflow_call"]["secrets"] == {
            "AZURE_CLIENT_ID": {"required": True}, "AZURE_TENANT_ID": {"required": True},
            "AZURE_SUBSCRIPTION_ID": {"required": False},
        }
    for workflow in (public, bundle, cohort):
        assert workflow["permissions"] == {"contents": "read", "id-token": "write"}
    # Forward the unresolved input across BOTH call boundaries. Resolve the fallback
    # only in workflow env, identically for root setup's scope hash and the cohort.
    assert callers[0]["with"]["resource-group"] == public["env"]["RESOURCE_GROUP"]
    assert callers[0]["with"]["subscription-id"] == "${{ inputs['subscription-id'] }}"
    for name in ("resource-group", "subscription-id", "dps-capacity-limit"):
        assert callers[1]["with"][name] == "${{ inputs['" + name + "'] }}"
    assert cohort["env"] == {
        "RESOURCE_GROUP": "${{ inputs['resource-group'] }}",
        "TEST_SUBSCRIPTION_ID": public["env"]["TEST_SUBSCRIPTION_ID"],
    }
    assert _triggers(public)["workflow_call"]["secrets"]["AZURE_SUBSCRIPTION_ID"] == {"required": True}
    assert _triggers(public)["workflow_call"]["inputs"]["subscription-id"]["default"] == ""
    assert set(_triggers(public)["workflow_dispatch"]["inputs"]) == {
        *(f"test{service}" for service in SERVICES),
        "adr-test-filter", "adr-revoke-certificates", "python-versions", "regions", "resource-group", "subscription-id",
        "dps-capacity-limit",
    }


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
    for workflow in _workflows():
        for job in workflow["jobs"].values():
            if "uses" in job:
                for name, value in job.get("with", {}).items():
                    assert _expression_contexts(value) <= allowed, (name, value)


@pytest.mark.parametrize("context", ["secrets", "env", "steps", "job", "runner"])
@pytest.mark.parametrize("access", [".VALUE", "['VALUE']"])
def test_expression_context_check_detects_unsupported_dot_and_bracket_access(context, access):
    assert _expression_contexts("${{ inputs['subscription-id'] || " + context + access + " }}") == {
        "inputs", context,
    }


@POSIX_WORKFLOW
@pytest.mark.parametrize("explicit,fallback", [
    (SUBSCRIPTION, None),  # Dispatch with explicit subscription and no fallback secret.
    ("", SUBSCRIPTION),  # Reusable caller with empty input and required root fallback.
    (SUBSCRIPTION, "unused-offline-fallback"),  # Explicit input wins at both ends.
])
def test_subscription_resolution_matches_setup_scope_and_cohort_login(tmp_path, explicit, fallback):
    public, bundle, cohort = _workflows()
    inherited = {"AZURE_CLIENT_ID": "offline-client", "AZURE_TENANT_ID": "offline-tenant"}
    if fallback is not None:
        inherited["AZURE_SUBSCRIPTION_ID"] = fallback

    def resolve(expression, input_value):
        # Evaluate only the literal references/disjunction used by this contract;
        # never eval arbitrary workflow or shell text.
        references = {
            "inputs['subscription-id']": input_value,
            "secrets.AZURE_SUBSCRIPTION_ID": inherited.get("AZURE_SUBSCRIPTION_ID", ""),
        }
        terms = expression.removeprefix("${{ ").removesuffix(" }}").split(" || ")
        return next((references[term] for term in terms if references[term]), "")

    setup_subscription = resolve(public["env"]["TEST_SUBSCRIPTION_ID"], explicit)
    forwarded = explicit
    for caller, callee in (
        (public["jobs"]["int-test"], bundle), (bundle["jobs"]["cohort"], cohort),
    ):
        forwarded = resolve(caller["with"]["subscription-id"], forwarded)
        assert forwarded == explicit  # In particular, an empty input stays empty.
        contract = _triggers(callee)["workflow_call"]
        assert all(name in inherited for name, spec in contract["secrets"].items() if spec["required"])
        assert contract["inputs"]["subscription-id"]["required"] is False
        assert caller["secrets"] == "inherit"
    live_subscription = resolve(cohort["env"]["TEST_SUBSCRIPTION_ID"], forwarded)
    assert setup_subscription == live_subscription == SUBSCRIPTION
    result, outputs = _matrix(tmp_path, TEST_SUBSCRIPTION_ID=setup_subscription)
    assert result.returncode == 0, result.stdout + result.stderr
    assert outputs["live-scope"] == hashlib.sha256(f"{live_subscription}/cli-int-test-rg".encode()).hexdigest()
    login = next(step for step in cohort["jobs"]["service"]["steps"] if step["name"] == "Az CLI login")
    assert login["with"]["subscription-id"] == "${{ env.TEST_SUBSCRIPTION_ID }}"


@POSIX_WORKFLOW
@pytest.mark.parametrize("services,pythons,regions", [
    ("auto", "3.13", "centraluseuap"),
    ("auto", "3.10,3.13", "centraluseuap"),  # Release caller: owned then ADU for EACH Python.
    ("ADR,DPS,ADU", "3.10,3.13", "centraluseuap,westus"),
    ("ADU,ADR", "3.13", "centraluseuap"),  # Input order cannot fold ADU into the parallel cohort.
    ("HubControl,HubData,DPS,ADR", "3.13", "centraluseuap"),
    ("ADR", "3.13", "centraluseuap"),
    ("ADU", "3.13", "centraluseuap"),
    ("ADU", "3.10,3.13", "centraluseuap,westus"),
])
def test_matrix_cohorts_preserve_every_selected_combination_once(tmp_path, services, pythons, regions):
    result, outputs = _matrix(
        tmp_path, INPUT_SERVICES=services, INPUT_PYTHON_VERSIONS=pythons, INPUT_REGIONS=regions,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    flat, cohorts = json.loads(outputs["matrix"]), json.loads(outputs["cohorts"])
    selected = SERVICES if services == "auto" else services.split(",")
    expected = set(itertools.product(selected, pythons.split(","), regions.split(",")))

    def identity(config):
        return config["service"], config["python"], config["region"]

    assert len(flat) == len(expected)
    assert {identity(config) for config in flat} == expected
    owned = set(selected) & OWNED_SERVICES
    group_services = ([owned] if owned else []) + ([{"ADU"}] if "ADU" in selected else [])
    pairs = sorted(itertools.product(pythons.split(","), regions.split(",")))
    assert len(cohorts) == len(pairs) * len(group_services)
    assert [
        (cohort["python"], cohort["region"], {config["service"] for config in cohort["configs"]})
        for cohort in cohorts
    ] == [(python, region, services) for python, region in pairs for services in group_services]
    assert Counter(identity(config) for cohort in cohorts for config in cohort["configs"]) == Counter(
        identity(config) for config in flat
    )
    ceilings = {"DPS": 150, "HubControl": 225, "HubData": 360, "ADU": 200, "ADR": 360}
    for cohort in cohorts:
        configs = cohort["configs"]
        actual_services = {config["service"] for config in configs}
        assert actual_services in group_services
        assert len(configs) == len(actual_services) <= 4
        assert actual_services <= OWNED_SERVICES or actual_services == {"ADU"}
        assert {(config["python"], config["region"]) for config in configs} == {
            (cohort["python"], cohort["region"]),
        }
        for config in configs:
            assert config["timeout"] == ceilings[config["service"]]
            assert config["tox_env"] == config["service"] + "-int"
    assert outputs["live-scope"] == hashlib.sha256(f"{SUBSCRIPTION}/cli-int-test-rg".encode()).hexdigest()


@POSIX_WORKFLOW
@pytest.mark.parametrize("overrides", [
    {"INPUT_SERVICES": "ADR,ADR"}, {"INPUT_SERVICES": "HubData,HubData"},
    {"INPUT_PYTHON_VERSIONS": "3.13, 3.13"}, {"INPUT_REGIONS": "centraluseuap,centraluseuap"},
    {"INPUT_SERVICES": "ADR,,DPS"}, {"INPUT_SERVICES": "ADR,"},
    {"INPUT_PYTHON_VERSIONS": "3.13,"}, {"INPUT_PYTHON_VERSIONS": "3.13\n3.10"},
    {"INPUT_REGIONS": "centraluseuap,"}, {"INPUT_REGIONS": "centraluseuap\nwestus"},
    {"INPUT_SERVICES": "HubWorkflows"}, {"INPUT_SERVICES": "HubLocalAuth"},
    {"INPUT_SERVICES": "ADR", "INPUT_REGIONS": ",".join(f"region{i}" for i in range(257))},
])
def test_matrix_rejects_duplicate_empty_or_oversized_inputs_instead_of_dropping_jobs(tmp_path, overrides):
    result, outputs = _matrix(tmp_path, **overrides)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "::error::" in result.stdout
    assert not outputs


@POSIX_WORKFLOW
@pytest.mark.parametrize("field", ["INPUT_SERVICES", "INPUT_PYTHON_VERSIONS", "INPUT_REGIONS"])
def test_matrix_inputs_are_not_evaluated_as_shell_or_injected_into_json(tmp_path, field):
    marker = tmp_path / "injected"
    result, outputs = _matrix(tmp_path, **{field: f"$(touch {marker})"})
    assert result.returncode != 0
    assert not outputs
    assert not marker.exists()


@POSIX_WORKFLOW
def test_scope_lock_identity_is_case_insensitive_and_independent_of_selected_cohorts(tmp_path):
    scopes = []
    for index, overrides in enumerate((
        {},
        {"INPUT_SERVICES": "ADR,DPS,ADU", "INPUT_PYTHON_VERSIONS": "3.10,3.13",
         "INPUT_REGIONS": "centraluseuap,westus"},
        {"INPUT_SERVICES": "ADR", "RESOURCE_GROUP": "CLI-INT-TEST-RG",
         "TEST_SUBSCRIPTION_ID": SUBSCRIPTION.upper()},
        {"INPUT_SERVICES": "ADR", "RESOURCE_GROUP": "different-offline-rg"},
        {"INPUT_SERVICES": "ADR", "TEST_SUBSCRIPTION_ID": "different-offline-subscription"},
    )):
        directory = tmp_path / str(index)
        directory.mkdir()
        result, outputs = _matrix(directory, **overrides)
        assert result.returncode == 0, result.stdout + result.stderr
        scopes.append(outputs["live-scope"])
    assert scopes[0] == scopes[1] == scopes[2]
    assert len({scopes[0], scopes[3], scopes[4]}) == 3


@POSIX_WORKFLOW
@pytest.mark.parametrize("selected", [(), ("ADR",), ("DPS", "HubControl", "HubData", "ADR"), SERVICES])
def test_dispatch_toggles_keep_adu_and_adr_selection_independent(tmp_path, selected):
    names = {"HubControl": "HUB_CONTROL", "HubData": "HUB_DATA"}
    result, outputs = _matrix(
        tmp_path, INPUT_SERVICES="",
        **{"INPUT_TEST_" + names.get(service, service): "true" for service in selected},
    )
    assert (result.returncode == 0) is bool(selected), result.stdout + result.stderr
    if selected:
        assert {row["service"] for row in json.loads(outputs["matrix"])} == set(selected)
    else:
        assert not outputs


def test_execution_and_result_shells_never_interpolate_raw_github_inputs():
    for workflow in _workflows():
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                if "run" in step:
                    assert "${{" not in step["run"], step["name"]
    job = _workflows()[2]["jobs"]["service"]
    assert job["timeout-minutes"] == "${{ matrix.config.timeout }}"
    assert job["env"] == {
        "TEST_SERVICE": "${{ matrix.config.service }}", "TEST_TOX_ENV": "${{ matrix.config.tox_env }}",
        "TEST_PYTHON": "${{ matrix.config.python }}", "TEST_REGION": "${{ matrix.config.region }}",
    }
    login = next(step for step in job["steps"] if step["name"] == "Az CLI login")
    assert login["with"]["subscription-id"] == "${{ env.TEST_SUBSCRIPTION_ID }}"


@POSIX_WORKFLOW
@pytest.mark.parametrize("status", ["success", "failure", "cancelled"])
@pytest.mark.parametrize("service", ["ADR", "ADU"])
def test_result_artifact_contract_survives_extraction_and_keeps_phase_evidence(tmp_path, status, service):
    public, _, cohort = _workflows()
    steps = {step["name"]: step for step in cohort["jobs"]["service"]["steps"]}
    for name in ("Record test result", "Upload test result", "Upload coverage artifact"):
        assert steps[name]["if"] == "${{ always() }}"
    record = steps["Record test result"]
    assert record["env"] == {"TEST_STATUS": "${{ job.status }}"}
    # Recording metadata must not delete/relocate controller-produced nested artifacts.
    result_dir = tmp_path / "test-result"
    for folder in ("hub-phases", "dps-phases"):
        evidence = result_dir / folder / "receipt.json"
        evidence.parent.mkdir(parents=True)
        evidence.write_text('{"preserve": true}', encoding="utf-8")
    (tmp_path / "test-output.log").write_text(
        "FAILED azext_iot/tests/adr/example_int.py::test_example - message\n", encoding="utf-8",
    )
    failure = "azext_iot/tests/adr/example_int.py::test_example"
    if service == "ADR":
        failure += " [case 1] - failed phase(s): call"
        (result_dir / "integration-outcomes.json").write_text('{"schema": 1, "session_finished": false}')
        (result_dir / "failures.txt").write_text(failure + "\n")
    result = subprocess.run(
        ["bash", "-c", record["run"]], cwd=tmp_path, capture_output=True, text=True, timeout=15, check=False,
        env=dict(os.environ, TEST_STATUS=status, TEST_SERVICE=service, TEST_PYTHON="3.13", TEST_REGION="centraluseuap"),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for field, value in {
        "status": status, "service": service, "python": "3.13", "region": "centraluseuap", "failures": failure,
    }.items():
        assert (result_dir / f"{field}.txt").read_text(encoding="utf-8") == value + "\n"
    if service == "ADR":
        assert (result_dir / "integration-outcomes.json").read_text() == '{"schema": 1, "session_finished": false}'
    for folder in ("hub-phases", "dps-phases"):
        assert (result_dir / folder / "receipt.json").read_text(encoding="utf-8") == '{"preserve": true}'
    suffix = "${{ matrix.config.service }}-py${{ matrix.config.python }}-${{ matrix.config.region }}"
    assert steps["Upload test result"]["with"] == {
        "name": "test-result-" + suffix, "overwrite": True, "path": "test-result/", "retention-days": 1,
    }
    assert steps["Upload coverage artifact"]["with"] == {
        "name": "coverage-" + suffix, "overwrite": True, "path": "./.coverage",
        "include-hidden-files": True, "retention-days": 30,
    }
    gate = public["jobs"]["int-test-gate"]
    evaluation = next(step for step in gate["steps"] if step["name"] == "Evaluate per-service results")
    assert evaluation["env"]["INTEGRATION_MATRIX"] == "${{ needs.setup.outputs.matrix || '[]' }}"
    assert evaluation["env"]["INTEGRATION_RESULT"] == "${{ needs.int-test.result }}"
    assert public["jobs"]["combine-coverage"]["needs"] == ["setup", "unit-test", "int-test", "int-test-gate"]


@POSIX_WORKFLOW
def test_all_changed_workflow_shells_parse_without_executing_live_commands():
    for workflow in _workflows():
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                if "run" in step:
                    result = subprocess.run(
                        ["bash", "-n"], input=step["run"], capture_output=True, text=True, timeout=10, check=False,
                    )
                    assert result.returncode == 0, step["name"] + ": " + result.stderr
