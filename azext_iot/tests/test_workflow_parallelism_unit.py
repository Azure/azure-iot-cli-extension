# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline topology, matrix and artifact contracts for flat integration jobs."""

from collections import Counter
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
FILES = ("int_test.yml",)
SERVICES = ("DPS", "HubControl", "HubData", "ADU", "ADR")
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


def test_flat_matrix_makes_all_combinations_concurrently_eligible_without_wrappers_or_locks():
    public = _workflows()[0]
    assert set(public["jobs"]) == {"setup", "unit-test", "int-test", "int-test-gate", "combine-coverage"}
    job = public["jobs"]["int-test"]
    assert job["needs"] == ["setup", "unit-test"]
    assert job["if"] == (
        "${{ needs.setup.result == 'success' && needs.unit-test.result == 'success' && "
        "(needs.setup.outputs.matrix || '[]') != '[]' }}"
    )  # No service-specific dependency or ADU eligibility restriction.
    assert not {"uses", "with", "secrets"}.intersection(job)
    assert job["runs-on"] == "ubuntu-latest"
    assert job["strategy"] == {
        "fail-fast": False, "matrix": {"config": "${{ fromJson(needs.setup.outputs.matrix || '[]') }}"},
    }
    assert public["jobs"]["setup"]["outputs"] == {"matrix": "${{ steps.matrix.outputs.matrix }}"}
    assert "concurrency" not in public
    for value in public["jobs"].values():
        assert "concurrency" not in value
        assert "max-parallel" not in value.get("strategy", {})
        assert not value.get("continue-on-error", False)
    for name in ("int_test_bundle.yml", "int_test_cohort.yml"):
        assert not (ROOT / ".github/workflows" / name).exists()


def test_public_inputs_remain_typed_with_oidc_and_shared_scope_environment():
    public = _workflows()[0]
    triggers = _triggers(public)
    assert set(triggers) == {"workflow_call", "workflow_dispatch"}
    for trigger in triggers.values():
        declared = trigger["inputs"]
        assert not {"adr-test-filter", "adr-revoke-certificates", "dps-capacity-limit"}.intersection(declared)
        for name in ("resource-group", "subscription-id", "python-versions", "regions"):
            assert declared[name]["type"] == "string" and declared[name]["required"] is False
        assert declared["resource-group"]["default"] == "cli-int-test-rg"
        assert declared["regions"]["default"] == "centraluseuap"
        assert declared["python-versions"]["default"] == "3.13"
    assert public["permissions"] == {"contents": "read", "id-token": "write"}
    assert public["env"] == {
        "RESOURCE_GROUP": "${{ inputs['resource-group'] || 'cli-int-test-rg' }}",
        "TEST_SUBSCRIPTION_ID": "${{ inputs['subscription-id'] || secrets.AZURE_SUBSCRIPTION_ID }}",
    }
    assert triggers["workflow_call"]["secrets"] == {
        name: {"required": True} for name in ("AZURE_CLIENT_ID", "AZURE_TENANT_ID", "AZURE_SUBSCRIPTION_ID")
    }
    assert triggers["workflow_call"]["inputs"]["subscription-id"]["default"] == ""
    assert triggers["workflow_call"]["inputs"]["test-services"]["default"] == "auto"
    dispatch = triggers["workflow_dispatch"]["inputs"]
    assert dispatch["subscription-id"]["default"] == SUBSCRIPTION
    for service in SERVICES:
        assert dispatch[f"test{service}"]["type"] == "boolean"
        assert dispatch[f"test{service}"]["default"] is True
    assert set(dispatch) == {
        *(f"test{service}" for service in SERVICES),
        "python-versions", "regions", "resource-group", "subscription-id",
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
    release = yaml.safe_load((ROOT / ".github/workflows/release_workflow.yml").read_text(encoding="utf-8"))
    for workflow in (*_workflows(), release):
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
def test_subscription_resolution_is_shared_by_setup_and_direct_service_login(tmp_path, explicit, fallback):
    public = _workflows()[0]
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
    assert setup_subscription == SUBSCRIPTION
    for name in ("setup", "int-test"):
        assert "TEST_SUBSCRIPTION_ID" not in public["jobs"][name].get("env", {})
        for step in public["jobs"][name]["steps"]:
            assert "TEST_SUBSCRIPTION_ID" not in step.get("env", {})
    result, outputs = _matrix(tmp_path, TEST_SUBSCRIPTION_ID=setup_subscription)
    assert result.returncode == 0, result.stdout + result.stderr
    assert set(outputs) == {"matrix"}
    login = next(step for step in public["jobs"]["int-test"]["steps"] if step["name"] == "Az CLI login")
    assert login["with"]["subscription-id"] == "${{ env.TEST_SUBSCRIPTION_ID }}"


@POSIX_WORKFLOW
@pytest.mark.parametrize("services,pythons,regions", [
    ("auto", "3.13", "centraluseuap"),
    ("auto", "3.10,3.13", "centraluseuap"),  # Release caller: all services for EACH Python.
    ("ADR,DPS,ADU", "3.10,3.13", "centraluseuap,westus"),
    ("ADU,ADR", "3.13", "centraluseuap"),  # ADU has the same eligibility as the other services.
    ("HubControl,HubData,DPS,ADR", "3.13", "centraluseuap"),
    ("ADR", "3.13", "centraluseuap"),
    ("ADU", "3.13", "centraluseuap"),
    ("ADU", "3.10,3.13", "centraluseuap,westus"),
])
def test_flat_matrix_preserves_exact_cartesian_membership_budgets_names_and_artifacts(tmp_path, services, pythons, regions):
    result, outputs = _matrix(
        tmp_path, INPUT_SERVICES=services, INPUT_PYTHON_VERSIONS=pythons, INPUT_REGIONS=regions,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert set(outputs) == {"matrix"}
    flat = json.loads(outputs["matrix"])
    selected = SERVICES if services == "auto" else services.split(",")
    expected = set(itertools.product(selected, pythons.split(","), regions.split(",")))

    def identity(config):
        return config["service"], config["python"], config["region"]

    assert Counter(identity(config) for config in flat) == Counter(expected)
    ceilings = {"DPS": 150, "HubControl": 225, "HubData": 360, "ADU": 200, "ADR": 360}
    job = _workflows()[0]["jobs"]["int-test"]
    uploads = [step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact@")]
    names, artifacts = [], []
    for config in flat:
        assert config["timeout"] == ceilings[config["service"]]
        assert config["tox_env"] == config["service"] + "-int"

        def render(template):
            for key, value in config.items():
                template = template.replace("${{ matrix.config." + key + " }}", str(value))
            assert "${{" not in template
            return template

        names.append(render(job["name"]))
        assert names[-1] == f"{config['service']} py{config['python']} ({config['region']})"
        for step in uploads:
            artifacts.append(render(step["with"]["name"]))
        assert artifacts[-2:] == [
            f"{prefix}-{config['service']}-py{config['python']}-{config['region']}"
            for prefix in ("test-result", "coverage")
        ]
    assert len(set(names)) == len(expected)
    assert len(set(artifacts)) == 2 * len(expected)


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
    job = _workflows()[0]["jobs"]["int-test"]
    assert job["timeout-minutes"] == "${{ matrix.config.timeout }}"
    assert job["env"] == {
        "TEST_SERVICE": "${{ matrix.config.service }}", "TEST_TOX_ENV": "${{ matrix.config.tox_env }}",
        "TEST_PYTHON": "${{ matrix.config.python }}", "TEST_REGION": "${{ matrix.config.region }}",
    }
    login = next(step for step in job["steps"] if step["name"] == "Az CLI login")
    assert login["with"]["subscription-id"] == "${{ env.TEST_SUBSCRIPTION_ID }}"


@POSIX_WORKFLOW
@pytest.mark.parametrize("status", ["success", "failure", "cancelled"])
@pytest.mark.parametrize("service", SERVICES)
def test_result_artifact_contract_keeps_phase_evidence_in_direct_jobs(tmp_path, status, service):
    public = _workflows()[0]
    steps = {step["name"]: step for step in public["jobs"]["int-test"]["steps"]}
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
