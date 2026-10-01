# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Cancellation-safe, metadata-only receipts for serial integration pytest runs."""

import json
import math
import os
from pathlib import Path


def case_label(nodeid):
    # Never persist parameter IDs, which may contain credentials. Separate case
    # numbers preserve parametrized-case identity without retaining their values.
    return nodeid.partition("[")[0]


class IntegrationResults:
    """Persist before returning from each hook, not only at session shutdown.

    Only code addresses, phase/outcome enums and numeric durations are allowed.
    Exception text, captured output, skip reasons and parameter values are
    deliberately excluded, rather than relying on error-message redaction.
    These receipts describe pytest execution, not Azure resource cleanup.
    """

    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.cases = {}
        self.session_finished = False
        self.exit_code = None
        self.persist()

    def select(self, nodeids):
        for nodeid in nodeids:
            self._case(nodeid)
        self.persist()

    def _case(self, nodeid):
        if nodeid not in self.cases:
            self.cases[nodeid] = {
                "case": len(self.cases) + 1, "nodeid": case_label(nodeid), "started": False, "reports": [],
            }
        return self.cases[nodeid]

    def start(self, nodeid):
        self._case(nodeid)["started"] = True
        self.persist()

    def report(self, report):
        case = self._case(report.nodeid)
        case["started"] = True
        duration = float(report.duration)
        case["reports"].append({
            "when": report.when if report.when in {"setup", "call", "teardown"} else "unknown",
            "outcome": report.outcome if report.outcome in {"passed", "failed", "skipped", "rerun"} else "unknown",
            "seconds": round(duration, 3) if math.isfinite(duration) else None,
        })
        self.persist()

    def finish(self, exit_code):
        self.exit_code = int(exit_code)
        self.session_finished = True
        self.persist()

    @staticmethod
    def _result(case):
        phases = {report["when"]: report["outcome"] for report in case["reports"]}
        complete = (
            "setup" in phases and "teardown" in phases
            and (phases["setup"] in {"failed", "skipped"} or "call" in phases)
        )
        outcomes = {report["outcome"] for report in case["reports"]}
        if outcomes - {"passed", "skipped"}:
            status = "failed"
        elif not complete:
            status = "incomplete" if case["started"] else "not_started"
        else:
            status = "skipped" if "skipped" in outcomes else "passed"
        return dict(case, complete=complete, status=status)

    def _write(self, name, text):
        target = self.directory / name
        temporary = target.with_suffix(target.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)

    def persist(self):
        cases = [self._result(case) for case in self.cases.values()]
        receipt = {
            "schema": 1, "session_finished": self.session_finished,
            "exit_code": self.exit_code, "selected": len(cases), "cases": cases,
        }
        failures = []
        if not self.session_finished:
            failures.append("Integration session incomplete; no terminal pytest result.")
        if self.exit_code not in (None, 0):
            failures.append(f"Integration session exited with code {self.exit_code}.")
        if not cases:
            failures.append("No selected integration cases were recorded.")
        for case in cases:
            label = f"{case['nodeid']} [case {case['case']}]"
            failed = [report["when"] for report in case["reports"]
                      if report["outcome"] not in {"passed", "skipped"}]
            if failed:
                failures.append(f"{label} - failed phase(s): {', '.join(failed)}")
            if not case["complete"]:
                failures.append(f"{label} - {'incomplete' if case['started'] else 'not started'}")
        # Until finish(), the previous failure file always has an incomplete
        # marker. Clear it only after the terminal receipt has been replaced.
        self._write("integration-outcomes.json", json.dumps(receipt, indent=2) + "\n")
        self._write("failures.txt", "".join(line + "\n" for line in failures))
