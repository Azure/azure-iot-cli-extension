# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Collect the complete unit inventory, then execute one deterministic file shard."""

from collections import Counter
import os
from pathlib import Path
import platform
import time

import pytest

from azext_iot.tests import _unit_shards as shards


def pytest_addoption(parser):
    parser.addoption("--unit-shard", type=int, choices=range(1, shards.COUNT + 1))
    parser.addoption("--unit-shard-output")


def pytest_configure(config):
    if not config.getoption("unit_shard") or not config.getoption("unit_shard_output"):
        raise pytest.UsageError("Unit sharding requires a shard number and a unique output directory.")
    if (config.getoption("numprocesses", None) not in (None, 0, "0") or config.getoption("reruns", 0)
            or config.getoption("keyword") != "_unit.py" or config.getoption("markexpr")
            or config.getoption("deselect", []) or config.getoption("lf", False)):
        raise pytest.UsageError("Unit shards require serial pytest, the complete _unit.py selection and no retries.")
    if [Path(arg).resolve() for arg in config.args] != [config.rootpath / "azext_iot/tests"]:
        raise pytest.UsageError("Unit shards must collect the complete azext_iot/tests directory.")
    config.pluginmanager.register(Receipt(config), "unit-shard-receipt")


class Receipt:
    def __init__(self, config):
        self.output = Path(config.getoption("unit_shard_output")).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.started = time.monotonic()
        self.profile = shards.read(shards.PROFILE)
        self.identities = {}
        self.data = {
            "schema": 1, "context": shards.context(), "python": platform.python_version(),
            "shard": config.getoption("unit_shard"), "attempt": int(os.environ["UNIT_ATTEMPT"]),
            "profile": shards.digest(self.profile), "inventory": [], "selected": [], "reports": {},
            "durations": {}, "finished": False, "exitstatus": None, "artifacts": {},
        }
        shards.write(self.output / "receipt.json", self.data, exclusive=True)

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, config, items):
        counts = Counter()
        for item in items:
            if not item.path.name.endswith("_unit.py"):
                raise pytest.UsageError("Non-unit cases matched the unit selection.")
            # Random parameter values differ between processes. Source function and
            # parameter position retain every case without persisting those values.
            base = item.nodeid.split("[", 1)[0]
            self.identities[item.nodeid] = f"{base}::{counts[base]}"
            counts[base] += 1
        inventory = sorted(self.identities.values())
        if len(inventory) != len(items):
            raise pytest.UsageError("Duplicate unit collection identities.")
        self.data["inventory"] = inventory
        plan = shards.partition([node.split("::", 1)[0] for node in inventory], self.profile)
        selected, dropped = [], []
        for item in items:
            name = item.nodeid.split("::", 1)[0]
            (selected if name in plan[self.data["shard"] - 1] else dropped).append(item)
        self.data["selected"] = sorted(self.identities[item.nodeid] for item in selected)
        items[:] = selected
        config.hook.pytest_deselected(items=dropped)
        shards.write(self.output / "receipt.json", self.data)

    def pytest_runtest_logreport(self, report):
        node = self.identities[report.nodeid]
        self.data["reports"].setdefault(node, {}).setdefault(report.when, []).append(report.outcome)
        name = node.split("::", 1)[0]
        self.data["durations"][name] = self.data["durations"].get(name, 0) + report.duration

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_sessionfinish(self, session, exitstatus):
        outcome = yield
        self.data["finished"] = outcome.excinfo is None
        self.data["exitstatus"] = int(session.exitstatus)
        self.data["seconds"] = time.monotonic() - self.started
        self.data["artifacts"] = {
            name: shards.file_digest(self.output / name) for name in shards.ARTIFACTS if (self.output / name).is_file()
        }
        shards.write(self.output / "receipt.json", self.data)
