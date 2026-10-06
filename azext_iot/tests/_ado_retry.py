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


class InfrastructureFailure(AssertionError):
    """Preserve existing assertion handling for service readiness failures."""


class CleanupFailure(InfrastructureFailure):
    """A call-phase cleanup failure needs independent resource-absence proof."""

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
        raise ValueError("Missing terminal pytest execution; start a new run after fixing infrastructure.")
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
        raise ValueError("Setup/teardown or call-phase cleanup failed without independent cleanup proof; start a new run.")
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


def evaluate(history, context):
    """Validate the entire chain; a later pass cannot erase an unsafe earlier attempt."""
    validate_context(context)
    previous = None
    expected = {}
    effective = {}
    recovered = set()
    remaining = {}
    for index, attempt in enumerate(history, 1):
        if attempt.get("schema") != 2:
            raise ValueError("Unsupported attempt format; start a new run with the updated runner.")
        if attempt.get("context") != context:
            changed = sorted(key for key in context if attempt.get("context", {}).get(key) != context[key])
            raise ValueError("Attempt identity changed: " + ", ".join(changed) + ". Start a new run.")
        if (attempt.get("sequence") != index
                or attempt.get("parent") != (digest(previous) if previous else None)
                or attempt.get("nativeAttempt") != index):
            raise ValueError("Attempt ancestry is missing or changed; start a new run.")
        if attempt.get("executionErrors") != []:
            raise ValueError("Prior attempt did not complete safely; see its rejection report and start a new run: "
                             + "; ".join(attempt.get("executionErrors") or ["Execution evidence is missing."]))
        phases = attempt["phases"]
        if attempt.get("reused") is True:
            if index == 1 or phases or any("failed" in values.values() for values in effective.values()):
                raise ValueError("Only fully passing evidence may be reused without test execution.")
            previous = attempt
            continue
        if not phases:
            raise ValueError("Attempt has no phase evidence.")
        if index == 1:
            expected = {phase: tuple(value["expected"]) for phase, value in phases.items()}
            if any(not nodes or len(set(nodes)) != len(nodes) for nodes in expected.values()):
                raise ValueError("Empty or duplicate original collection.")
        elif set(phases) != {phase for phase, values in effective.items() if "failed" in values.values()}:
            raise ValueError("Retry must cover exactly the remaining failed phases.")
        for phase, value in phases.items():
            if phase not in expected or tuple(value["expected"]) != expected[phase] or value["safe"] is not True:
                raise ValueError("Collection changed or phase cleanup is unproven.")
            excluded = value.get("excluded", [])
            if (excluded != history[0]["phases"][phase].get("excluded", [])
                    or len(set(excluded)) != len(excluded) or set(excluded).intersection(expected[phase])):
                raise ValueError("Committed skip exclusions changed or overlap enabled coverage.")
            selected = set(expected[phase]) if index == 1 else set(remaining[phase])
            allow_fixture_failures = (
                context["service"] in ("DPS", "HubControl", "HubData") and value.get("cleanupVerified") is True
            )
            results = outcomes(value["receipt"], allow_fixture_failures=allow_fixture_failures)
            if set(results) != selected:
                raise ValueError("Retry did not execute exactly the required failed cases or fixture phase.")
            if index > 1:
                recovered.update((phase, node) for node, status in results.items()
                                 if status == "passed" and effective[phase][node] == "failed")
                recovered.difference_update((phase, node) for node, status in results.items() if status == "failed")
            effective.setdefault(phase, {}).update(results)
            remaining[phase] = (list(expected[phase]) if fixture_failure(value["receipt"]) else
                                [node for node, status in effective[phase].items() if status == "failed"])
        previous = attempt
    return expected, effective, recovered


def pending(history, context):
    _, effective, _ = evaluate(history, context)
    latest = {phase: value for attempt in history for phase, value in attempt["phases"].items()}
    return {
        phase: (list(latest[phase]["expected"]) if fixture_failure(latest[phase]["receipt"]) else
                [node for node, status in cases.items() if status == "failed"])
        for phase, cases in effective.items() if "failed" in cases.values()
    }


def load_history(directory, context):
    paths = sorted(Path(directory).rglob("attempt.json"))
    relevant = []
    for path in paths:
        record = read(path)
        candidate = record.get("context", {})
        if all(candidate.get(key) == context[key] for key in ("service", "python", "region")):
            verify_artifacts(path, record)
            relevant.append(record)
    relevant.sort(key=lambda value: value["sequence"])
    evaluate(relevant, context)
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
    _, effective, recovered = evaluate(history, context)
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
    excluded = 0
    for phase, value in history[0]["phases"].items():
        for node in value.get("excluded", []):
            excluded += 1
            case = ET.SubElement(suite, "testcase", classname=phase, name=node)
            ET.SubElement(case, "skipped", message="Committed unconditional skip; not counted as passed coverage.")
    suite.set("tests", str(sum(map(len, effective.values())) + excluded))
    suite.set("skipped", str(excluded))
    suite.set("failures", str(failures))
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)
    return failures
