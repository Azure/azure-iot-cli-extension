# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Immutable, manual-only ADO attempt ledger. No Azure or pytest imports."""

import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

STAGES = ("setup", "call", "teardown")
SERVICES = ("DPS", "HubControl", "HubData", "ADU", "ADR")


class IntegrityError(ValueError):
    """Changed immutable identity or artifacts cannot be recovered in the same run."""


class InfrastructureFailure(AssertionError):
    """Preserve existing assertion handling for service readiness failures."""


class CleanupFailure(InfrastructureFailure):
    """A call-phase cleanup failure requires full-service recovery."""

    _iot_cleanup_failed = True


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)


def case_id(node):
    # Parameter values can contain secrets. Resolve hashes back to nodes only in pytest collection.
    return hashlib.sha256(node.encode()).hexdigest()


def retryable_failure(error):
    pending_errors, seen = [error], set()
    while pending_errors:
        current = pending_errors.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        if getattr(current, "_iot_cleanup_failed", False):
            return False
        pending_errors.extend((current.__cause__, current.__context__))
    return True


def fixture_failure(receipt):
    return any(
        stages.get("setup") != ["passed"] or stages.get("teardown") != ["passed"]
        or stages.get("call") == ["failed"] and receipt.get("retryableFailures", {}).get(node) is False
        for node, stages in receipt["reports"].items()
    )


def outcomes(receipt, *, allow_fixture_failures=False):
    if receipt.get("finished") is not True or receipt.get("exitstatus") not in (0, 1):
        raise ValueError("Missing terminal pytest execution; full-service recovery is required.")
    if receipt.get("workerErrors"):
        raise ValueError("Worker execution or collection evidence is incomplete.")
    selected, reports = receipt["collected"], receipt["reports"]
    if not selected or len(set(selected)) != len(selected) or set(reports) != set(selected):
        raise ValueError("Missing, duplicate or unexpected test evidence.")
    result = {}
    for node in selected:
        stages = reports[node]
        setup_failed = stages.get("setup") == ["failed"]
        if (set(stages) != ({"setup", "teardown"} if setup_failed else set(STAGES))
                or stages.get("setup") not in (["passed"], ["failed"])
                or stages.get("teardown") not in (["passed"], ["failed"])
                or not setup_failed and stages.get("call") not in (["passed"], ["failed"])):
            raise ValueError("Skipped, duplicate or incomplete test stages cannot qualify a retry.")
        if stages.get("call") == ["failed"] and type(receipt.get("retryableFailures", {}).get(node)) is not bool:
            raise ValueError("Failed call classification is missing.")
        result[node] = "failed" if ["failed"] in stages.values() else "passed"
    if fixture_failure(receipt) and not allow_fixture_failures:
        raise ValueError("Setup/teardown or call-phase cleanup failed; full-service recovery is required.")
    if receipt["exitstatus"] != (1 if "failed" in result.values() else 0):
        raise ValueError("Pytest exit status disagrees with case evidence.")
    return result


def validate_context(context):
    required = {"build", "definition", "commit", "wheel", "dependencies", "service", "python", "region",
                "endpoint", "subscription", "resource_group", "diagnostic"}
    if set(context) != required or not all(isinstance(context[key], str) and context[key] for key in required):
        raise ValueError("Incomplete attempt identity.")
    if context["service"] not in (*SERVICES, "RetrySelfTest") or context["diagnostic"] not in ("true", "false"):
        raise ValueError("Unknown service/diagnostic identity.")
    if (context["service"] == "RetrySelfTest") != (context["diagnostic"] == "true"):
        raise ValueError("Diagnostic evidence cannot qualify an integration service.")
    if context["definition"] != "147":
        raise ValueError("Attempt evidence belongs to a different pipeline definition.")
    for key in ("wheel", "dependencies"):
        if not re.fullmatch("[a-f0-9]{64}", context[key]):
            raise ValueError("Artifact/dependency identity is invalid.")


def _evaluate(history, context):
    """Keep immutable history while requiring a full service after incomplete execution."""
    validate_context(context)
    previous = None
    expected = {}
    effective = {}
    recovered = set()
    full_required = not history
    native_attempt = 0
    for index, attempt in enumerate(history, 1):
        if attempt.get("schema") != 3:
            raise ValueError("Unsupported attempt format; start a new run with the updated runner.")
        if attempt.get("context") != context:
            changed = sorted(key for key in context if attempt.get("context", {}).get(key) != context[key])
            raise ValueError("Attempt identity changed: " + ", ".join(changed) + ". Start a new run.")
        native = attempt.get("nativeAttempt")
        if (attempt.get("sequence") != index or type(native) is not int or native <= native_attempt
                or attempt.get("parent") != (digest(previous) if previous else None)):
            raise ValueError("Attempt ancestry is missing or changed; start a new run.")
        missing = list(range(native_attempt + 1, native))
        if attempt.get("missingAttempts", []) != missing:
            raise ValueError("Missing native attempts were not explicitly recorded.")
        mode = attempt.get("mode")
        if mode not in ("full", "cases", "reuse") or (
                (index == 1 or full_required or missing) and mode != "full"):
            raise ValueError("Incomplete execution or missing attempts require a full-service retry.")
        native_attempt = native
        phases = attempt["phases"]
        execution_errors = attempt.get("executionErrors")
        if not isinstance(execution_errors, list):
            raise ValueError("Attempt execution status is missing.")
        if mode == "reuse":
            if execution_errors or not effective or phases or any("failed" in values.values() for values in effective.values()):
                raise ValueError("Only fully passing evidence may be reused without test execution.")
            previous = attempt
            continue
        if execution_errors or not phases:
            full_required = True
            previous = attempt
            continue
        collection = {phase: tuple(value["expected"]) for phase, value in phases.items()}
        if any(not nodes or len(set(nodes)) != len(nodes) for nodes in collection.values()):
            raise ValueError("Empty or duplicate original collection.")
        if mode == "full" and expected and collection != expected:
            raise ValueError("Full-service retry collection changed.")
        if mode == "cases" and set(phases) != {
                phase for phase, values in effective.items() if "failed" in values.values()}:
            raise ValueError("Retry must cover exactly the remaining failed phases.")
        next_effective = {} if mode == "full" else {phase: dict(values) for phase, values in effective.items()}
        full_required = False
        for phase, value in phases.items():
            if value["safe"] is not True:
                raise ValueError("Phase isolation or execution identity is unproven.")
            if mode == "cases" and (phase not in expected or collection[phase] != expected[phase]):
                raise ValueError("Retry collection changed.")
            excluded = value.get("excluded", [])
            original = next((item["phases"][phase] for item in history[:index]
                             if phase in item["phases"] and not item.get("executionErrors")), value)
            if (excluded != original.get("excluded", []) or len(set(excluded)) != len(excluded)
                    or set(excluded).intersection(collection[phase])):
                raise ValueError("Committed skip exclusions changed or overlap enabled coverage.")
            selected = (set(collection[phase]) if mode == "full" else
                        {node for node, status in effective[phase].items() if status == "failed"})
            try:
                results = outcomes(value["receipt"], allow_fixture_failures=True)
            except ValueError:
                full_required = True
                continue
            if set(results) != selected:
                raise ValueError("Retry did not execute exactly the required cases.")
            full_required = full_required or fixture_failure(value["receipt"])
            if index > 1:
                recovered.update((phase, node) for node, status in results.items()
                                 if status == "passed" and effective.get(phase, {}).get(node) == "failed")
                recovered.difference_update((phase, node) for node, status in results.items() if status == "failed")
            next_effective.setdefault(phase, {}).update(results)
        if mode == "full":
            expected = collection
        effective = next_effective
        previous = attempt
    return expected, effective, recovered, full_required


def evaluate(history, context):
    return _evaluate(history, context)[:3]


def recovery_plan(history, context):
    expected, effective, _, full_required = _evaluate(history, context)
    if not history or full_required:
        return {"mode": "full", "phases": {phase: list(nodes) for phase, nodes in expected.items()}}
    phases = {phase: [node for node, status in cases.items() if status == "failed"]
              for phase, cases in effective.items() if "failed" in cases.values()}
    return {"mode": "cases" if phases else "reuse", "phases": phases}


def pending(history, context):
    plan = recovery_plan(history, context)
    return plan["phases"] or ({"tests": []} if plan["mode"] == "full" else {})


def load_history(directory, context):
    for path in Path(directory).rglob("rejection.json"):
        rejected = read(path)
        identity = rejected.get("identity", {})
        if not rejected.get("recoverable") and (
                not identity or all(identity.get(key) == context[key] for key in ("service", "python", "region"))):
            raise IntegrityError("An immutable identity/artifact check failed; start a new run.")
    paths = sorted(Path(directory).rglob("attempt.json"))
    relevant = []
    for path in paths:
        record = read(path)
        candidate = record.get("context", {})
        if all(candidate.get(key) == context[key] for key in ("service", "python", "region")):
            try:
                verify_artifacts(path, record)
            except (ValueError, OSError, KeyError) as error:
                raise IntegrityError("Original attempt artifacts are missing or changed.") from error
            relevant.append(record)
    relevant.sort(key=lambda value: value["sequence"])
    try:
        evaluate(relevant, context)
    except ValueError as error:
        raise IntegrityError(str(error)) from error
    return relevant


def evidence(directory):
    directory = Path(directory)
    return {path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.rglob("*")) if path.is_file()}


def verify_artifacts(path, record):
    directory = Path(path).parent
    hashes = record.get("evidence")
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("Raw attempt evidence is missing.")
    for name, expected in hashes.items():
        source = directory / name
        if (source.resolve().is_relative_to(directory.resolve()) is False or not source.is_file()
                or hashlib.sha256(source.read_bytes()).hexdigest() != expected):
            raise ValueError("Raw attempt evidence is missing or changed.")
    for phase, value in record["phases"].items():
        name = phase + "/phase.json"
        if name not in hashes or read(directory / name) != value:
            raise ValueError("Attempt ledger disagrees with its phase evidence.")


def junit(history, context, path):
    _, effective, recovered, full_required = _evaluate(history, context)
    suite = ET.Element("testsuite", name=context["service"])
    failures = 0
    for phase, cases in effective.items():
        for node, status in cases.items():
            case = ET.SubElement(suite, "testcase", classname=phase, name=node)
            if status != "passed":
                failures += 1
                ET.SubElement(case, "failure", message="Unresolved test failure; see immutable attempt artifacts.")
            elif (phase, node) in recovered:
                ET.SubElement(case, "system-out").text = "Passed on manual retry; initial failure remains in attempt history."
    if full_required:
        failures += 1
        case = ET.SubElement(suite, "testcase", classname="pipeline", name="Full-service recovery required")
        ET.SubElement(case, "error", message="Incomplete execution or fixture failure; rerun the affected service.")
    excluded = 0
    latest = {phase: value for attempt in history for phase, value in attempt["phases"].items()}
    for phase, value in latest.items():
        for node in value.get("excluded", []):
            excluded += 1
            case = ET.SubElement(suite, "testcase", classname=phase, name=node)
            ET.SubElement(case, "skipped", message="Committed unconditional skip; not counted as passed coverage.")
    suite.set("tests", str(sum(map(len, effective.values())) + excluded + int(full_required)))
    suite.set("skipped", str(excluded))
    suite.set("failures", str(failures - int(full_required)))
    suite.set("errors", str(int(full_required)))
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)
    return failures
