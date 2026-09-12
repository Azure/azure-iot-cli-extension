#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.

"""Fail closed when any expected integration result or prerequisite is unsuccessful."""

import argparse
import json
import os
from pathlib import Path
import runpy
import xml.etree.ElementTree as ET


COMBINATION_FIELDS = ("service", "python", "region")
MANIFEST = runpy.run_path(str(Path(__file__).resolve().parents[1] / "azext_iot/tests/dps/_phase_manifest.py"))


def evaluate_dps_phases(result_dir):
    """Do not trust a green job/last tox exit without both phases and cleanup evidence."""
    errors = []
    try:
        receipt = json.loads((result_dir / "dps-phases.json").read_text(encoding="utf-8"))
        phases = receipt["phases"]
        if (receipt["schema"] != 1 or receipt["status"] != "passed"
                or [phase["name"] for phase in phases] != ["regular", "service-sas"]
                or not receipt["baseline"]["capacity"]["ready"]):
            raise ValueError("incomplete/failed two-phase summary")
        baseline = {resource["id"].lower() for resource in receipt["baseline"]["resources"]}
        for phase in phases:
            name = phase["name"]
            folder = result_dir / "dps-phases" / name
            if json.loads((folder / "result.json").read_text(encoding="utf-8")) != phase:
                raise ValueError(f"{name}: phase result differs from aggregate")
            if not (folder / "output.log").is_file():
                raise ValueError(f"{name}: missing redacted phase log")
            cleanup = phase["cleanup"]
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
            cases = list(ET.parse(folder / "junit.xml").getroot().iter("testcase"))
            expected = MANIFEST["expected_nodeids"](name)
            identities = [MANIFEST["junit_nodeid"](case) for case in cases]
            selections = [json.loads(path.read_text(encoding="utf-8"))
                          for path in (folder / "receipts").glob("selection-*.json")]
            if (not results["valid"] or not cases or len(cases) != results["selected"]
                    or len(cases) != len(expected) or set(identities) != expected
                    or results["nodeids"] != sorted(expected) or not selections
                    or any(value.get("nodeids") != sorted(expected) or value.get("selected") != len(expected)
                           for value in selections)
                    or results["passed"] != len(expected) or results["failures"] or results["errors"] or results["skipped"]
                    or any(any(case.find(outcome) is not None for outcome in ("failure", "error", "skipped")) for case in cases)):
                raise ValueError(f"{name}: missing/incomplete/failed JUnit results")
            if name == "service-sas":
                gate = phase["gate"]
                capacity = gate["capacity"]
                if (len(cases) != 29 or results["passed"] != 29 or results["skipped"]
                        or any(case.find("skipped") is not None for case in cases)
                        or gate["previous_owned_absent"] is not True or capacity["ready"] is not True
                        or capacity["count"] != len(set(capacity["ids"]))
                        or capacity["required"] != 2 or capacity["count"] + 2 > capacity["limit"]):
                    raise ValueError("service-sas: missing coverage or failed pre-phase cleanup/capacity gate")
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
        errors.append(f"DPS phase evidence is incomplete or unsuccessful: {error}.")
    return errors


def _combination(values):
    result = tuple(values.get(field) for field in COMBINATION_FIELDS)
    if not all(isinstance(value, str) and value.strip() for value in result):
        raise ValueError("Each test combination requires a service, Python version, and region.")
    return result


def evaluate_results(results_dir, matrix, job_results):
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
            errors.extend(evaluate_dps_phases(result_dir))
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
    )
    print(summary, end="")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as output:
            output.write(summary)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
