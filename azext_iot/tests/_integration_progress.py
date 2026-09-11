# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from dataclasses import dataclass
from threading import Event, Lock, Thread
from time import monotonic

import pytest


@dataclass
class _ActiveTest:
    started: float
    phase_started: float
    phase: str = "setup"


class IntegrationProgress:
    """Report controller-side phase metadata without exposing captured command output."""

    def __init__(self, config, interval, clock=monotonic):
        self.config = config
        self.interval = interval
        self.clock = clock
        self._active = {}
        self._lock = Lock()
        self._stop = Event()
        self._thread = None
        self._reporter = None

    @staticmethod
    def _is_integration(nodeid):
        return nodeid.partition("::")[0].endswith("_int.py")

    @staticmethod
    def _label(nodeid):
        # Parameter IDs can contain credentials; only display the test's code address.
        return nodeid.partition("[")[0]

    def _write(self, message):
        self._reporter.write_line(f"[integration progress] {message}")
        self._reporter.flush()

    def pytest_sessionstart(self):
        if self.interval <= 0 or hasattr(self.config, "workerinput"):
            return
        self._reporter = self.config.pluginmanager.getplugin("terminalreporter")
        if self._reporter is None:
            return
        self._thread = Thread(target=self._heartbeat, name="iot-integration-progress", daemon=True)
        self._thread.start()

    def pytest_runtest_logstart(self, nodeid):
        if self._reporter is None or not self._is_integration(nodeid):
            return
        with self._lock:
            now = self.clock()
            self._active[nodeid] = _ActiveTest(now, now)
            self._write(f"START setup: {self._label(nodeid)}")

    def pytest_runtest_logreport(self, report):
        if self._reporter is None or not self._is_integration(report.nodeid):
            return
        with self._lock:
            active = self._active.get(report.nodeid)
            if active is None:
                return
            self._write(
                f"END {report.when} {report.outcome}: {self._label(report.nodeid)} "
                f"({report.duration:.1f}s)"
            )
            if report.when in ("setup", "call"):
                active.phase = "call" if report.when == "setup" and report.outcome == "passed" else "teardown"
                active.phase_started = self.clock()
            else:
                self._active.pop(report.nodeid)

    def pytest_runtest_logfinish(self, nodeid):
        with self._lock:
            self._active.pop(nodeid, None)

    def _heartbeat(self):
        while not self._stop.wait(self.interval):
            with self._lock:
                if not self._active:
                    self._write("No active integration test reported; collecting or awaiting workers.")
                    continue
                now = self.clock()
                self._write(
                    f"{len(self._active)} active test(s); elapsed time is not proof of service progress."
                )
                for nodeid, active in sorted(self._active.items()):
                    self._write(
                        f"WAIT {active.phase}: {self._label(nodeid)} | "
                        f"test {now - active.started:.1f}s, phase {now - active.phase_started:.1f}s "
                        "without a completed phase report"
                    )

    def _shutdown(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
            self._thread = None

    @pytest.hookimpl(tryfirst=True)
    def pytest_sessionfinish(self):
        self._shutdown()

    def pytest_unconfigure(self):
        self._shutdown()
