# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Stage frozen health-test sources and reuse the native IoT integration controller."""

import argparse
import os
from pathlib import Path
import runpy
import shutil

from release_monitor import verify_bundle, write_json


ROOT = Path(__file__).resolve().parents[1]


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
    # Keep selected cases and fixtures; overlay only the current controller protocol.
    for path in (ROOT / "azext_iot/tests").glob("_*.py"):
        if (path.name == "__init__.py" or path.name.endswith("_manifest.py")
                or path.name.startswith("_release_")
                or path.name.startswith("_unit_") and manifest.get("kind") != "source"):
            continue
        destination = output / path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    shutil.copyfile(ROOT / "tox.ini", output / "tox.ini")
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
