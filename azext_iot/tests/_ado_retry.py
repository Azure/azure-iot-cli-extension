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
from urllib.parse import unquote, urlsplit

STAGES = ("setup", "call", "teardown")
SERVICES = ("DPS", "HubControl", "HubData", "ADU", "ADR")


class InfrastructureFailure(AssertionError):
    """Preserve existing assertion handling without permitting targeted recovery."""


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


def assertion_failure(error):
    return (type(error) is AssertionError and error.__cause__ is None and error.__context__ is None
            and not getattr(error, "_iot_cleanup_failed", False))


def resource_root(url, scope):
    """Identify a top-level ARM resource without retaining query strings or credentials."""
    parsed = urlsplit(url)
    if parsed.hostname not in ("management.azure.com", "centraluseuap.management.azure.com"):
        return None
    path = unquote(parsed.path).casefold()
    if not path.startswith("/subscriptions/"):
        return None
    prefix = f"/subscriptions/{scope['subscription']}/resourcegroups/{scope['resource_group']}/providers/".casefold()
    parts = path.strip("/").split("/")
    if (parsed.scheme != "https" or parsed.username or parsed.password or not path.startswith(prefix)
            or len(parts) < 8 or any(part in ("", ".", "..") for part in parts)):
        raise ValueError("ARM mutation is outside the test resource scope.")
    if parts[5:7] == ["microsoft.resources", "deployments"]:
        raise ValueError("Indirect ARM deployments cannot establish per-process resource inventory.")
    return "/" + "/".join(parts[:8])


def cleanup_inventory(before, after, receipt, scope):
    roots = receipt.get("resourceRoots")
    if (receipt.get("resourceScope") != scope or not isinstance(roots, list)
            or any(not isinstance(root, str) for root in roots) or roots != sorted(set(roots))
            or any(resource_root("https://management.azure.com" + root, scope) != root for root in roots)):
        raise ValueError("Per-process resource observation is missing or invalid.")
    new_resources = set(after) - set(before)
    remaining = sorted(resource for resource in new_resources
                       if any(resource == root or resource.startswith(root + "/") for root in roots))
    return {"scope": scope, "observedRoots": roots, "before": before, "after": after,
            "remaining": remaining, "complete": not remaining}


def outcomes(receipt):
    if receipt.get("finished") is not True or receipt.get("exitstatus") not in (0, 1):
        raise ValueError("Missing terminal pytest execution; rerun the full diagnostic after fixing infrastructure.")
    selected, reports = receipt["collected"], receipt["reports"]
    if not selected or len(set(selected)) != len(selected) or set(reports) != set(selected):
        raise ValueError("Missing, duplicate or unexpected test evidence.")
    result = {}
    for node in selected:
        stages = reports[node]
        if (set(stages) != set(STAGES) or stages["setup"] != ["passed"] or stages["teardown"] != ["passed"]
                or stages["call"] not in (["passed"], ["failed"])):
            raise ValueError("Setup, teardown, skipped or incomplete cases cannot be recovered by targeted retry.")
        result[node] = stages["call"][0]
        if result[node] == "failed" and receipt.get("retryableFailures", {}).get(node) is not True:
            raise ValueError("Unclassified/authentication/infrastructure failure cannot be recovered by targeted retry.")
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
    for index, attempt in enumerate(history, 1):
        if (attempt.get("schema") != 1 or attempt.get("context") != context or attempt.get("sequence") != index
                or attempt.get("parent") != (digest(previous) if previous else None)
                or attempt.get("nativeAttempt") != index or attempt.get("healthy") is not True):
            raise ValueError("Attempt identity, ancestry, infrastructure or cleanup evidence is invalid.")
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
            selected = (set(expected[phase]) if index == 1 else
                        {node for node, status in effective[phase].items() if status == "failed"})
            results = outcomes(value["receipt"])
            if set(results) != selected:
                raise ValueError("Retry executed something other than the exact failed cases.")
            if index > 1:
                recovered.update((phase, node) for node, status in results.items() if status == "passed")
            effective.setdefault(phase, {}).update(results)
        previous = attempt
    return expected, effective, recovered


def pending(history, context):
    _, effective, _ = evaluate(history, context)
    return {phase: [node for node, status in cases.items() if status == "failed"]
            for phase, cases in effective.items() if "failed" in cases.values()}


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
