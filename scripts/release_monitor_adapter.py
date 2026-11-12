# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Stage frozen health-test sources and reuse the native IoT integration controller."""

import argparse
import ast
import hashlib
import os
from pathlib import Path
import runpy
import shutil

from release_monitor import verify_bundle, write_json


ROOT = Path(__file__).resolve().parents[1]
COMPATIBILITY = {
    "azext_iot/tests/dps/conftest.py": {
        "symbols": (
            "_readiness_http_error", "_data_plane_authorization_pending",
            "_readiness_service_code", "_readiness_diagnostic", "_wait_for_readiness",
            "_wait_for_current_user_data_plane",
        ),
        "helpers": ("_dps_authorization_failed_response",),
        "imports": ("import re", "from msrestazure.azure_exceptions import CloudError"),
        "reason": (
            "Allow ten minutes for Fairfax Hub caller authorization and retain safe per-probe timing receipts; "
            "preserve DPS deadlines, exact error predicates and three-success confirmation."
        ),
    },
    "azext_iot/tests/iothub/_sas_phase.py": {
        "symbols": ("HubSasPhase.install",),
        "imports": (
            "from urllib.parse import parse_qs",
            "from azext_iot.tests._integration_target import CLOUDS, arm_hosts, cloud",
        ),
        "reason": "Observe sovereign ARM and Storage mutations without changing SAS cases or cleanup assertions.",
    },
}


def function(tree, symbol):
    node = tree
    for name in symbol.split("."):
        matches = [item for item in node.body if isinstance(item, (ast.ClassDef, ast.FunctionDef)) and item.name == name]
        if len(matches) != 1:
            raise ValueError(f"Selected source cannot apply the reviewed test adapter: {symbol}")
        node = matches[0]
    if not isinstance(node, ast.FunctionDef):
        raise ValueError(f"Test adapter does not target a function: {symbol}")
    return node


def adapt_harness(output, manifest):
    """Replace only reviewed instrumentation functions, retaining all other frozen source."""
    changes = []
    for relative, adapter in COMPATIBILITY.items():
        path = output / relative
        if not path.exists():
            continue
        original = path.read_text(encoding="utf-8")
        current = (ROOT / relative).read_text(encoding="utf-8")
        tree, donor = ast.parse(original), ast.parse(current)
        lines, replacements = original.splitlines(keepends=True), []
        symbols = adapter["symbols"] + adapter.get("helpers", ())
        for symbol in symbols:
            replacement = function(donor, symbol)
            missing_helper = symbol in adapter.get("helpers", ()) and not any(
                getattr(item, "name", None) == symbol for item in tree.body
            )
            previous = None if missing_helper else function(tree, symbol)
            if (replacement.decorator_list or previous is not None
                    and (ast.dump(previous.args) != ast.dump(replacement.args) or previous.decorator_list)):
                raise ValueError(f"Selected source has an incompatible test-adapter signature: {symbol}")
            content = current.splitlines(keepends=True)[replacement.lineno - 1:replacement.end_lineno]
            replacements.append((
                previous.lineno - 1 if previous else len(lines), previous.end_lineno if previous else len(lines),
                content if previous else ["\n\n", *content, "\n"],
            ))
        for start, end, replacement in sorted(replacements, reverse=True):
            lines[start:end] = replacement
        text = "".join(lines)
        tree = ast.parse(text)
        imports = {
            (getattr(node, "module", None), alias.name, alias.asname)
            for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names
        }
        additions = []
        for statement in adapter["imports"]:
            node = ast.parse(statement).body[0]
            if any((getattr(node, "module", None), alias.name, alias.asname) not in imports for alias in node.names):
                additions.append(statement + "\n")
        if additions:
            first = next(node for node in tree.body if not (
                isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
                or isinstance(node, ast.ImportFrom) and node.module == "__future__"
            ))
            lines = text.splitlines(keepends=True)
            lines[first.lineno - 1:first.lineno - 1] = additions
            text = "".join(lines)
        ast.parse(text)
        if text != original:
            path.write_text(text, encoding="utf-8")
            changes.append({
                "path": relative, "symbols": list(symbols), "reason": adapter["reason"],
                "originalSha256": hashlib.sha256(original.encode()).hexdigest(),
                "adaptedSha256": hashlib.sha256(text.encode()).hexdigest(),
            })
    return {
        "version": 1, "sourceCommit": manifest["testSourceCommit"],
        "automationCommit": manifest["automationCommit"], "files": changes,
    }


def stage(bundle, output, *, source_only=False):
    bundle, output = Path(bundle).resolve(), Path(output).resolve()
    manifest = verify_bundle(
        bundle, require_wheel=not source_only, extension="azure-iot", automation_commit=os.environ["BUILD_SOURCEVERSION"],
        cloud=os.environ["MONITOR_CLOUD"], track=os.environ["MONITOR_TRACK"], slot=os.environ["MONITOR_TRACK"],
    )
    if output.exists():
        raise ValueError("Monitor test workspace must be fresh for this attempt.")
    source = bundle / "source"
    if any(path.is_symlink() for path in source.rglob("*")):
        raise ValueError("Released source must not contain symbolic links.")
    shutil.copytree(source, output, ignore=shutil.ignore_patterns(".git"))
    # Keep selected cases and fixtures; controller overlays and the narrow adapters
    # below are independently recorded, never a replacement of the released product.
    for path in (ROOT / "azext_iot/tests").glob("_*.py"):
        if (path.name == "__init__.py" or path.name.endswith("_manifest.py")
                or path.name.startswith("_release_")
                or path.name.startswith("_unit_") and manifest.get("kind") != "source"):
            continue
        destination = output / path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    shutil.copyfile(ROOT / "tox.ini", output / "tox.ini")
    if not source_only:
        # Build/unit stages retain the original fixtures and their matching unit
        # doubles. These transport adapters apply only to live execution and its gate.
        compatibility = adapt_harness(output, manifest)
        manifest = {**manifest, "testCompatibility": compatibility}
        for change in compatibility["files"]:
            print(f"Test-only compatibility: {change['path']}: {change['reason']}", flush=True)
    write_json(output / "release-monitor.json", manifest)
    return manifest


def plan(bundle, output):
    stage(bundle, output, source_only=True)
    native = runpy.run_path(str(Path(output) / "azext_iot/tests/_ado_pipeline.py"))
    jobs = native["plan"](
        os.environ["MONITOR_SERVICES"].split(","), os.environ["MONITOR_PYTHONS"].split(","),
        os.environ["MONITOR_REGION"].split(","),
        os.environ["MONITOR_ENDPOINT"],
    )
    # Resolve the full version-specific selection before an Azure service connection is used.
    for job in jobs:
        for nodes in native["owned_nodes"](job["service"], job["endpoint"]).values():
            for node in nodes:
                path = Path(output) / node.split("::", maxsplit=1)[0]
                if not path.is_file():
                    raise ValueError(f"Released test source cannot execute the selected native cohort: {node}")
    write_json(Path(bundle) / "plan.json", jobs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "stage"])
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-only", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "plan":
        plan(args.bundle, args.output)
    else:
        stage(args.bundle, args.output, source_only=args.source_only)


if __name__ == "__main__":
    main()
