# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Import-free, explicit selection contract for non-qualifying live debugging."""

import hashlib
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[2]
ENV = "azext_iot_debug_selection"
DPS_ARGS_ENV = "azext_iot_dps_node_args"
DPS_PREFIX = "azext_iot/tests/dps/"


def select(suite, phase=None, nodes=None):
    if phase is None and not nodes:
        return None
    if not isinstance(phase, str) or not isinstance(nodes, (list, tuple)) or not nodes:
        raise ValueError("Focused live debugging requires --debug-phase and at least one --debug-node.")
    if any(not isinstance(node, str) for node in nodes) or len(set(nodes)) != len(nodes):
        raise ValueError("Debug nodes must be distinct exact repository-relative pytest node IDs.")
    if suite == "DPS":
        manifest = runpy.run_path(str(ROOT / "azext_iot/tests/dps/_phase_manifest.py"))
        allowed = tuple(sorted(DPS_PREFIX + node for node in manifest["expected_nodeids"](phase)))
    elif suite in ("HubControl", "HubData"):
        manifest = runpy.run_path(str(ROOT / "azext_iot/tests/_hub_suite_manifest.py"))
        allowed = manifest["nodes"](suite, phase)  # No linked-metadata opt-in in this entry point.
    else:
        raise ValueError("Unknown focused live suite.")
    if not set(nodes).issubset(allowed):
        raise ValueError("Debug selection contains unknown, excluded or out-of-phase nodes.")
    return {
        "suite": suite, "phase": phase, "requestedNodes": [node for node in allowed if node in nodes],
        "manifestSha256": hashlib.sha256(json.dumps(allowed).encode("utf-8")).hexdigest(),
    }


def from_environment(environment, suite, phase):
    raw = environment.get(ENV)
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid focused live selection envelope.") from error
    if not isinstance(value, dict) or value.get("suite") != suite or value.get("phase") != phase:
        raise ValueError("Focused live selection suite/auth phase mismatch.")
    expected = select(suite, phase, value.get("requestedNodes"))
    if value != expected:
        raise ValueError("Focused live selection does not match this checkout's manifest.")
    return expected


def provenance(debug):
    return {"mode": "debug", "qualifiesFullSuite": False, "debug": debug} if debug else {}


def matches(evidence, debug):
    if not isinstance(evidence, dict):
        return False
    if debug:
        return all(evidence.get(key) == value for key, value in provenance(debug).items())
    return (
        evidence.get("mode", "full") == "full"
        and evidence.get("qualifiesFullSuite", True) is True and "debug" not in evidence
    )


def add_arguments(parser):
    parser.add_argument("--debug-phase", help="Run only this auth phase as non-qualifying live debug evidence.")
    parser.add_argument("--debug-node", action="append",
                        help="Exact manifest-known repo-relative pytest node ID; repeat to select several cases.")
