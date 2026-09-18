# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Fail closed when any expected integration result or prerequisite is unsuccessful."""

import argparse
import json
import os
from pathlib import Path
import runpy
import xml.etree.ElementTree as ET


COMBINATION_FIELDS = ("service", "python", "region")
MANIFEST = runpy.run_path(str(Path(__file__).resolve().parents[2] / "azext_iot/tests/dps/_phase_manifest.py"))
FOCUSED = runpy.run_path(str(Path(__file__).resolve().with_name("_focused_live.py")))


def evaluate_dps_phases(result_dir, *, expected_capacity_limit=MANIFEST["DPS_LIMIT"]):
    """Do not trust a green job/last tox exit without every phase and cleanup evidence."""
    expected_capacity_limit = MANIFEST["parse_capacity_limit"](expected_capacity_limit)
    errors = []
    try:
        receipt = json.loads((result_dir / "dps-phases.json").read_text(encoding="utf-8"))
        phases = receipt["phases"]
        if not FOCUSED["matches"](receipt, None):
            raise ValueError("focused/debug evidence cannot qualify the full DPS suite")
        if (receipt["schema"] != 1 or receipt["status"] != "passed"
                or [phase["name"] for phase in phases] != list(MANIFEST["PHASE_NAMES"])
                or not receipt["baseline"]["capacity"]["ready"]):
            raise ValueError("incomplete/failed DPS phase summary")
        baseline = {resource["id"].lower() for resource in receipt["baseline"]["resources"]}
        admission = receipt["baseline"]["capacity"]
        if (admission["required"] != MANIFEST["REQUIRED_DPS_SLOTS"]
                or type(admission["limit"]) is not int or admission["limit"] != expected_capacity_limit
                or admission["count"] != len(baseline) or set(admission["ids"]) != baseline
                or admission["count"] + admission["required"] > expected_capacity_limit):
            raise ValueError("full DPS qualification requires two-slot admission under the trusted expected limit")
        for phase in phases:
            if not FOCUSED["matches"](phase, None):
                raise ValueError("focused/debug phase cannot qualify the full DPS suite")
            name = phase["name"]
            folder = result_dir / "dps-phases" / name
            if json.loads((folder / "result.json").read_text(encoding="utf-8")) != phase:
                raise ValueError(f"{name}: phase result differs from aggregate")
            if not (folder / "output.log").is_file():
                raise ValueError(f"{name}: missing redacted phase log")
            stages = folder / "receipts" / "pytest.json"
            if stages.exists() and not FOCUSED["matches"](json.loads(stages.read_text(encoding="utf-8")), None):
                raise ValueError("focused/debug stage evidence cannot qualify the full DPS suite")
            cleanup = phase["cleanup"]
            if (cleanup["capacity"]["required"] != MANIFEST["REQUIRED_DPS_SLOTS"]
                    or type(cleanup["capacity"]["limit"]) is not int
                    or cleanup["capacity"]["limit"] != expected_capacity_limit):
                raise ValueError(f"{name}: cleanup capacity policy does not match full qualification")
            owned = cleanup["owned_ids"]
            if (phase["status"] != "passed" or phase["exit_code"] != 0
                    or phase["timed_out"] is not False or phase["interrupted"] is not False
                    or cleanup["complete"] is not True or cleanup["remaining"] != []
                    or not owned or set(owned) != set(cleanup["absent_ids"])
                    or baseline.intersection(resource.lower() for resource in owned)):
                raise ValueError(f"{name}: unsuccessful execution or unproven owned-resource cleanup")
            for resource in owned:
                if not any(
                    json.loads(path.read_text(encoding="utf-8")).get("id") == resource
                    for path in (folder / "receipts").glob("owned-*.json")
                ):
                    raise ValueError(f"{name}: missing pre-create ownership receipt")
            results = phase["results"]
            junit = ET.parse(folder / "junit.xml").getroot()
            cases = list(junit.iter("testcase"))
            if junit.get("mode", "full") != "full":
                raise ValueError("focused/debug JUnit cannot qualify the full DPS suite")
            expected = MANIFEST["expected_nodeids"](name)
            identities = [MANIFEST["junit_nodeid"](case) for case in cases]
            selections = [json.loads(path.read_text(encoding="utf-8"))
                          for path in (folder / "receipts").glob("selection-*.json")]
            if (not results["valid"] or not cases or len(cases) != results["selected"]
                    or len(cases) != len(expected) or set(identities) != expected
                    or results["nodeids"] != sorted(expected) or not selections
                    or any(value.get("nodeids") != sorted(expected) or value.get("selected") != len(expected)
                           or not FOCUSED["matches"](value, None)
                           for value in selections)
                    or results["passed"] != len(expected) or results["failures"] or results["errors"] or results["skipped"]
                    or any(any(case.find(outcome) is not None for outcome in ("failure", "error", "skipped")) for case in cases)):
                raise ValueError(f"{name}: missing/incomplete/failed JUnit results")
            if name != "regular":
                gate = phase["gate"]
                capacity = gate["capacity"]
                required = 1 if name == "local-auth-toggle" else 2
                if (results["passed"] != len(expected) or results["skipped"]
                        or any(case.find("skipped") is not None for case in cases)
                        or gate["previous_owned_absent"] is not True or capacity["ready"] is not True
                        or capacity["count"] != len(set(capacity["ids"]))
                        or type(capacity["limit"]) is not int or capacity["limit"] != expected_capacity_limit
                        or capacity["required"] != required or capacity["count"] + required > expected_capacity_limit):
                    raise ValueError(f"{name}: missing coverage or failed pre-phase cleanup/capacity gate")
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
        errors.append(f"DPS phase evidence is incomplete or unsuccessful: {error}.")
    return errors


def _combination(values):
    result = tuple(values.get(field) for field in COMBINATION_FIELDS)
    if not all(isinstance(value, str) and value.strip() for value in result):
        raise ValueError("Each test combination requires a service, Python version, and region.")
    return result


def evaluate_hub_result(result_dir, service):
    """Bind authoritative phase evidence to the scheduled suite, not just a green job."""
    try:
        folder = result_dir / "hub-phases"
        receipt = json.loads((folder / "hub-phases.json").read_text(encoding="utf-8"))
        if receipt["suite"] != service:
            return [f"{service}: Hub phase summary suite does not match the scheduled service."]
        controller = runpy.run_path(str(Path(__file__).resolve().with_name("_hub_phase_runner.py")))
        result = controller["evaluate_hub_phases"](folder)
        if result["passed"] is not True or result["errors"]:
            return [f"{service}: Hub phase evidence is incomplete or unsuccessful."] + result["errors"]
    except (OSError, ValueError, KeyError, TypeError):
        return [f"{service}: missing or malformed Hub phase evidence."]
    return []


def evaluate_results(results_dir, matrix, job_results, *, expected_dps_capacity_limit=MANIFEST["DPS_LIMIT"]):
    expected_dps_capacity_limit = MANIFEST["parse_capacity_limit"](expected_dps_capacity_limit)
    errors = []
    summary = [
        "## Integration Test Results",
        "| Service | Python | Region | Result |",
        "|---------|--------|--------|--------|",
    ]
    for job, status in job_results.items():
        if status != "success":
            errors.append(f"Job '{job}' did not succeed: {status or 'missing result'}.")

    expected = {_combination(config) for config in matrix}
    if not expected:
        errors.append("No integration test combinations were scheduled.")
    if len(expected) != len(matrix):
        errors.append("The integration matrix contains duplicate combinations.")

    seen = set()
    # download-artifact extracts a single matching artifact directly into the root.
    for status_path in sorted(Path(results_dir).rglob("status.txt")):
        result_dir = status_path.parent
        try:
            values = {
                field: (result_dir / f"{field}.txt").read_text(encoding="utf-8").strip()
                for field in COMBINATION_FIELDS
            }
            combination = _combination(values)
        except (FileNotFoundError, ValueError) as error:
            errors.append(f"Invalid result artifact '{result_dir}': {error}")
            continue
        service, python, region = combination
        status = status_path.read_text(encoding="utf-8").strip()
        summary.append(f"| {service} | {python} | {region} | {status or 'missing result'} |")
        if combination not in expected:
            errors.append(f"Unexpected result for {service} / {python} / {region}.")
        if combination in seen:
            errors.append(f"Duplicate result for {service} / {python} / {region}.")
        seen.add(combination)
        if service == "DPS":
            errors.extend(evaluate_dps_phases(result_dir, expected_capacity_limit=expected_dps_capacity_limit))
        if service in ("HubControl", "HubData"):
            errors.extend(evaluate_hub_result(result_dir, service))
        if status != "success":
            errors.append(f"{service} / {python} / {region} did not succeed: {status or 'missing result'}.")

        failures_path = result_dir / "failures.txt"
        failures = failures_path.read_text(encoding="utf-8").strip() if failures_path.exists() else ""
        if failures:
            summary.extend(["", f"### Failed tests: {service} / {python} / {region}", "```", failures, "```"])
            if status == "success":
                errors.append(f"{service} / {python} / {region} reports success but contains failed tests.")

    for service, python, region in sorted(expected - seen):
        errors.append(f"Missing result for {service} / {python} / {region}.")
    summary.append("")
    if errors:
        summary.append("### FAILED - every scheduled combination and prerequisite must succeed")
        summary.extend(f"- {error}" for error in errors)
    else:
        summary.append("### Passed - every scheduled combination and prerequisite succeeded")
    return "\n".join(summary) + "\n", errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--expected-dps-capacity-limit", type=MANIFEST["parse_capacity_limit"],
                        default=MANIFEST["DPS_LIMIT"],
                        help="Trusted operator/workflow DPS limit; never infer it from result artifacts (default: 10).")
    args = parser.parse_args()
    matrix = json.loads(os.environ["INTEGRATION_MATRIX"])
    if not isinstance(matrix, list) or not all(isinstance(config, dict) for config in matrix):
        raise ValueError("INTEGRATION_MATRIX must be a JSON array of test combinations.")
    summary, errors = evaluate_results(
        args.results_dir,
        matrix,
        {
            "setup": os.environ.get("SETUP_RESULT"),
            "unit-test": os.environ.get("UNIT_TEST_RESULT"),
            "int-test": os.environ.get("INTEGRATION_RESULT"),
            "gate preparation": os.environ.get("GATE_JOB_RESULT"),
        },
        expected_dps_capacity_limit=args.expected_dps_capacity_limit,
    )
    print(summary, end="")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as output:
            output.write(summary)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
