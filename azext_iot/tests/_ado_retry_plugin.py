# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Exact collection fingerprints and metadata-only evidence for ADU/ADR and offline diagnostics."""

import json
import os
from pathlib import Path

import pytest

from azext_iot.tests._ado_retry import retryable_failure, case_id


def pytest_configure(config):
    path = os.environ.get("azext_iot_ado_receipt")
    if not path:
        raise pytest.UsageError("ADO retry plugin requires an explicit receipt path.")
    if config.getoption("reruns", 0):
        raise pytest.UsageError("Automatic test retries are disabled in pipeline 147.")
    receipt = Receipt(Path(path))
    config.pluginmanager.register(receipt, "ado-retry-receipt")


class Receipt:
    def __init__(self, path):
        self.path = path
        self.data = {
            "finished": False, "exitstatus": None, "expected": [], "collected": [], "reports": {},
            "excluded": [], "retryableFailures": {},
        }
        self.expected = json.loads(os.environ.get("azext_iot_ado_expected", "[]"))
        self.selected = json.loads(os.environ.get("azext_iot_ado_selected", "[]"))
        self.worker = os.getenv("PYTEST_XDIST_WORKER")
        self.worker_collection = None
        if not self.worker:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as stream:
                json.dump(self.data, stream)

    def save(self):
        if not self.worker:
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            temporary.replace(self.path)

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, session, config, items):
        excluded = [item for item in items if list(item.iter_markers("skip"))]
        enabled = [item for item in items if item not in excluded]
        nodes = [case_id(item.nodeid) for item in enabled]
        if not nodes or len(set(nodes)) != len(nodes) or self.expected and nodes != self.expected:
            raise pytest.UsageError("Original test collection is missing, duplicated or changed.")
        if self.selected and (len(set(self.selected)) != len(self.selected) or not set(self.selected) <= set(nodes)):
            raise pytest.UsageError("Retry selection is not an exact subset of the original collection.")
        self.data["expected"] = nodes
        self.data["excluded"] = [case_id(item.nodeid) for item in excluded]
        selected, dropped = [], excluded
        for item in enabled:
            (selected if not self.selected or case_id(item.nodeid) in self.selected else dropped).append(item)
        items[:] = selected
        config.hook.pytest_deselected(items=dropped)
        self.data["collected"] = [case_id(item.nodeid) for item in items]
        self.save()

    @pytest.hookimpl(optionalhook=True)
    def pytest_xdist_node_collection_finished(self, node, ids):
        selected = [case_id(value) for value in ids]
        if self.data["collected"] and selected != self.data["collected"]:
            raise pytest.UsageError("Worker selections disagree.")
        self.data["collected"] = selected
        self.save()

    @pytest.hookimpl(optionalhook=True)
    def pytest_testnodedown(self, node, error):
        value = getattr(node, "workeroutput", {}).get("ado_receipt", {})
        collection = (value.get("expected"), value.get("excluded"))
        if (error or value.get("finished") is not True or value.get("exitstatus") not in (0, 1)
                or not collection[0] or not isinstance(collection[1], list)
                or self.worker_collection is not None and self.worker_collection != collection
                or value.get("collected") != self.data["collected"]):
            self.data.setdefault("workerErrors", []).append("Worker execution or collection evidence is incomplete.")
        else:
            self.worker_collection = collection
            self.data["expected"], self.data["excluded"] = collection
        self.save()

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        report = (yield).get_result()
        if report.when == "call" and report.failed:
            if call.excinfo:
                report.user_properties.append(("ado_retryable", retryable_failure(call.excinfo.value)))

    def pytest_runtest_logreport(self, report):
        key = case_id(report.nodeid)
        outcome = "xfail" if hasattr(report, "wasxfail") else report.outcome
        self.data["reports"].setdefault(key, {}).setdefault(report.when, []).append(outcome)
        if report.when == "call" and report.failed:
            classifications = [value for name, value in report.user_properties if name == "ado_retryable"]
            self.data["retryableFailures"][key] = classifications[0] if len(classifications) == 1 else None
        self.save()

    @pytest.hookimpl(hookwrapper=True, trylast=True, specname="pytest_sessionfinish")
    def pytest_worker_sessionfinish(self, session):
        outcome = yield
        if self.worker:
            session.config.workeroutput["ado_receipt"] = {
                key: self.data[key] for key in ("expected", "excluded", "collected")
            }
            session.config.workeroutput["ado_receipt"].update(
                finished=outcome.excinfo is None, exitstatus=int(session.exitstatus),
            )

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_sessionfinish(self, session, exitstatus):
        outcome = yield
        self.data["finished"] = outcome.excinfo is None
        self.data["exitstatus"] = int(session.exitstatus)
        if self.data.get("workerErrors") and not session.exitstatus:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
            self.data["exitstatus"] = int(session.exitstatus)
        self.save()
