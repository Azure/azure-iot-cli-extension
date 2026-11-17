# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.

"""Restore a run's separate Python and extension dependency sets before retrying tests."""

import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys


PRODUCTS = {"azure-iot", "azure-iot-ops"}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def package_inventory(path=None):
    packages = {}
    installed = metadata.distributions(path=[str(path)]) if path else metadata.distributions()
    for package in installed:
        name = re.sub(r"[-_.]+", "-", package.metadata["Name"]).lower()
        version = package.version
        if (not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
                or not re.fullmatch(r"[A-Za-z0-9.!+_-]+", version) or name in packages):
            raise ValueError("Invalid or ambiguous installed dependency metadata.")
        if package.read_text("direct_url.json") and name not in PRODUCTS:
            raise ValueError(f"Cannot restore non-index dependency {name} using a version constraint.")
        text = package.read_text("METADATA")
        if not text:
            raise ValueError(f"Missing dependency metadata for {name}.")
        packages[name] = {
            "version": version, "metadata": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
    if not packages:
        raise ValueError("Cannot freeze an empty dependency environment.")
    return packages


def identity(key, wheel):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", key):
        raise ValueError("Invalid dependency environment key.")
    wheel = Path(wheel)
    wheels = list(wheel.glob("*.whl")) if wheel.is_dir() else [wheel]
    if len(wheels) != 1 or not wheels[0].is_file() or wheels[0].suffix != ".whl":
        raise ValueError("Exactly one original candidate wheel is required.")
    values = {name: os.environ[name] for name in ("BUILD_BUILDID", "SYSTEM_DEFINITIONID", "BUILD_SOURCEVERSION")}
    if (not all(re.fullmatch(r"[1-9][0-9]*", values[name]) for name in ("BUILD_BUILDID", "SYSTEM_DEFINITIONID"))
            or not re.fullmatch(r"[0-9a-f]{40}", values["BUILD_SOURCEVERSION"])):
        raise ValueError("Dependency snapshots require an immutable pipeline identity.")
    return {
        **values, "key": key, "python": list(sys.version_info[:2]),
        "platform": sys.platform, "architecture": platform.machine(),
        "wheel": hashlib.sha256(wheels[0].read_bytes()).hexdigest(),
    }


def validate(value, expected, environments):
    if (value.get("schema") != 1 or value.get("identity") != expected
            or set(value.get("environments", {})) != set(environments)):
        raise ValueError("Dependency snapshot belongs to another run, candidate, or environment.")
    for packages in value["environments"].values():
        if not isinstance(packages, dict) or not packages:
            raise ValueError("Dependency snapshot is incomplete.")
        for name, package in packages.items():
            if (not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
                    or not re.fullmatch(r"[A-Za-z0-9.!+_-]+", package["version"])
                    or not re.fullmatch(r"[0-9a-f]{64}", package["metadata"])):
                raise ValueError("Invalid dependency snapshot package.")
    return value


def constraints(output, environments):
    for name, packages in environments.items():
        if not re.fullmatch(r"[a-z][a-z0-9-]*", name):
            raise ValueError("Invalid dependency environment name.")
        (output / f"{name}.txt").write_text(
            "".join(f"{package}=={value['version']}\n" for package, value in sorted(packages.items())
                    if package not in PRODUCTS),
            encoding="utf-8",
        )


def restore(history, output, key, wheel, environments, attempt):
    expected = identity(key, wheel)
    paths = sorted(Path(history).glob(f"dependencies-{key}-*/lock.json"))
    values = [validate(read(path), expected, environments) for path in paths]
    if values and any(value != values[0] for value in values):
        raise ValueError("Dependency snapshots changed between attempts; start a new run.")
    if not values and attempt != 1:
        raise ValueError("A retry cannot resolve dependencies without its original snapshot.")
    output.mkdir(parents=True, exist_ok=False)
    constraints(output, values[0]["environments"] if values else {name: {} for name in environments})
    if values:
        write(output / "lock.json", values[0])


def capture(output, key, wheel, interpreters, targets):
    expected = identity(key, wheel)
    if set(interpreters) & set(targets):
        raise ValueError("Dependency environment names must be distinct.")
    environments = {}
    for name, executable, path in (
        [(name, executable, None) for name, executable in interpreters.items()]
        + [(name, sys.executable, path) for name, path in targets.items()]
    ):
        args = [executable, str(Path(__file__).resolve()), "inventory"]
        if path:
            if not Path(path).is_dir():
                raise ValueError(f"Installed dependency target {name} is missing.")
            args += ["--path", path]
        # Extension PYTHONPATH overlays must not contaminate the host interpreter's lock.
        env = {name: value for name, value in os.environ.items() if name != "PYTHONPATH"}
        environments[name] = json.loads(subprocess.check_output(args, env=env, text=True))
    value = validate({"schema": 1, "identity": expected, "environments": environments}, expected, environments)
    previous = output / "lock.json"
    if previous.exists() and validate(read(previous), expected, environments) != value:
        raise ValueError("Restored dependencies differ from the original snapshot; refusing to run tests.")
    constraints(output, environments)
    write(previous, value)
    print("##vso[task.setvariable variable=dependencyLockReady]true")


def mappings(values):
    result = {}
    for value in values:
        name, separator, path = value.partition("=")
        if (not separator or not path or name in result
                or not re.fullmatch(r"[a-z][a-z0-9-]*", name)):
            raise ValueError("Use distinct environment=path arguments.")
        result[name] = path
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inventory = commands.add_parser("inventory")
    inventory.add_argument("--path", type=Path)
    for operation in ("restore", "capture"):
        command = commands.add_parser(operation)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--key", required=True)
        command.add_argument("--wheel", type=Path, required=True)
        if operation == "restore":
            command.add_argument("--history", type=Path, required=True)
            command.add_argument("--environment", action="append", required=True)
            command.add_argument("--attempt", type=int, required=True)
        else:
            command.add_argument("--python", action="append", default=[])
            command.add_argument("--target", action="append", default=[])
    args = parser.parse_args(argv)
    if args.command == "inventory":
        print(json.dumps(package_inventory(args.path), sort_keys=True))
    elif args.command == "restore":
        restore(args.history, args.output, args.key, args.wheel, args.environment, args.attempt)
    else:
        capture(args.output, args.key, args.wheel, mappings(args.python), mappings(args.target))


if __name__ == "__main__":
    main()
