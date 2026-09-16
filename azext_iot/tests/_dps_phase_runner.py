# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Linux-only regular -> service-SAS -> local-auth-toggle DPS orchestration with ownership/capacity gates."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import runpy
import select
import shlex
import signal
import subprocess
import sys
import tempfile
from threading import Event, Thread, current_thread, main_thread
import time
from urllib.parse import urlsplit, parse_qs
from uuid import UUID, uuid4
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
ARM = "https://centraluseuap.management.azure.com"
PHASES = (
    ("regular", 20 * 60, 5 * 60),
    ("service-sas", 40 * 60, 10 * 60),
    ("local-auth-toggle", 20 * 60, 5 * 60),
)
RUNNER_SECONDS = 110 * 60
READ_SECONDS = 60
DPS_LIMIT = 10  # Conservative subscription default; the DPS SDK exposes no quota-read operation.
REQUIRED_SLOTS = 3  # Two shared DPS fixtures plus one sequential capacity-validation resource.
MANIFEST = runpy.run_path(str(ROOT / "azext_iot/tests/dps/_phase_manifest.py"))
FOCUSED = runpy.run_path(str(ROOT / "azext_iot/tests/_focused_live.py"))


class PhaseError(RuntimeError):
    """A prerequisite/receipt is missing; do not guess or mutate resources to recover."""


def require_linux():
    if sys.platform != "linux":
        raise PhaseError("DPS phase orchestration requires Linux: signals, process groups, /proc and pipe polling.")


def utc():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


class Redactor:
    """Redact before either streaming or writing; never persist a raw child log."""

    def __init__(self):
        self.private_key = False

    def line(self, text):
        if "-----BEGIN " in text and "PRIVATE KEY-----" in text:
            self.private_key = True
        if self.private_key:
            if "-----END " in text and "PRIVATE KEY-----" in text:
                self.private_key = False
            return "[private key material omitted]\n"
        text = re.sub(r"(?i)SharedAccessSignature\s+[^'\"\s]+", "***", text)
        text = re.sub(r"(?i)(SharedAccessKey|AccountKey|sig)=([^;&\s'\"<>]+)", r"\1=***", text)
        text = re.sub(
            r"""(?ix)((?:["']?(?:primary[_]?key|secondary[_]?key|access[_]?token|refresh[_]?token|
            authorization|client[_]?secret|connection[_]?string)["']?)\s*[:=]\s*)
            (?:"[^"]*"|'[^']*'|[^\s,;}]+)""", r"\1'***'", text,
        )
        text = re.sub(
            r"""(?i)((?:--(?:pk|sk|key|login|connection-string)|(?<!\w)-l)(?:=|\s+))
            (?:"[^"]*"|'[^']*'|[^\s]+)""".replace("\n            ", ""),
            r"\1***", text,
        )
        text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "***", text)
        # Service keys and PEM lines can appear as bare values in assertion tracebacks.
        return re.sub(r"(?<![A-Za-z0-9+/])(?:[A-Za-z0-9+/]{40,}={0,2})(?![A-Za-z0-9+/])", "***", text)


@contextmanager
def bounded_read(deadline=None):
    started = time.monotonic()
    seconds = READ_SECONDS if deadline is None else min(READ_SECONDS, deadline - started)
    if seconds <= 0:
        raise PhaseError("Read-only verification budget exhausted.")
    require_linux()
    alarm = getattr(signal, "SIGALRM", None)
    timer = getattr(signal, "ITIMER_REAL", None)
    set_timer = getattr(signal, "setitimer", None)
    get_timer = getattr(signal, "getitimer", None)
    if alarm is None or timer is None or not callable(set_timer) or not callable(get_timer):
        raise PhaseError("DPS read bounds require POSIX interval timers.")
    timer_started = time.monotonic()
    remaining, interval = get_timer(timer)
    outer_deadline = timer_started + remaining if remaining else None
    outer_fired = False

    def expired(signum, frame):
        nonlocal outer_fired, outer_deadline
        if outer_deadline is not None and (not outer_fired or interval) and time.monotonic() >= outer_deadline:
            outer_fired = True
            # Preserve pytest's timeout exception/meaning, not a read-bound error.
            if callable(previous):
                previous(signum, frame)
            elif previous != signal.SIG_IGN:
                signal.signal(alarm, previous)
                signal.raise_signal(alarm)
            if interval:
                outer_deadline += interval * (1 + int((time.monotonic() - outer_deadline) // interval))
            left = started + seconds - time.monotonic()
            if interval:
                left = min(left, outer_deadline - time.monotonic())
            set_timer(timer, max(0.000001, left))
            return
        raise PhaseError("Read-only ARM/authentication operation exceeded its 60-second bound.")

    previous = signal.signal(alarm, expired)
    try:
        read_deadline = started + seconds
        limit = min(read_deadline, outer_deadline) if outer_deadline is not None else read_deadline
        set_timer(timer, max(0.000001, limit - time.monotonic()))
        yield
    finally:
        set_timer(timer, 0)
        signal.signal(alarm, previous)
        if outer_deadline is not None and (not outer_fired or interval):
            left = outer_deadline - time.monotonic()
            if outer_fired and interval:
                left = interval - ((time.monotonic() - outer_deadline) % interval)
            # setitimer(0) cancels; an elapsed outer deadline must fire immediately.
            set_timer(timer, max(0.000001, left), interval)


def bounded_read_call(operation, deadline=None):
    """Bound a read-only callable, including authentication and response decoding.

    Worker callers cannot own process timers. Isolate their read from observer
    state and stop waiting at the absolute deadline. The checkpoint prevents a
    late authentication/read result from starting another request or page.
    """
    require_linux()
    limit = min(float("inf") if deadline is None else deadline, time.monotonic() + READ_SECONDS)
    cancelled, done = Event(), Event()
    result, errors = [], []

    def checkpoint():
        if cancelled.is_set() or time.monotonic() >= limit:
            raise PhaseError("Read-only verification budget exhausted.")

    checkpoint()
    if current_thread() is main_thread():
        with bounded_read(limit):
            return operation(checkpoint)

    def read():
        try:
            checkpoint()
            result.append(operation(checkpoint))
        except BaseException as error:  # Transfer the worker's failure to its caller, never swallow it.
            errors.append(error)
        finally:
            done.set()

    thread = Thread(target=read, name="hub-ownership-read", daemon=True)
    thread.start()
    try:
        if not done.wait(max(0, limit - time.monotonic())) or time.monotonic() >= limit:
            raise PhaseError("Read-only ARM/authentication operation exceeded its 60-second bound.")
        if errors:
            raise errors[0]
        return result[0]
    finally:
        cancelled.set()


class ArmReader:
    """Current branch SDKs, explicit subscription/audience, GET-only canary transport."""

    def __init__(self, subscription):
        sys.path.insert(0, str(ROOT))
        from azure.cli.core import get_default_cli
        from azure.cli.core._profile import Profile
        from azure.core.credentials import AccessToken
        from azure.core.pipeline.transport import RequestsTransport
        from azext_iot._factory import _ADR_DPS_API_VERSION, _ADR_IOT_HUB_API_VERSION
        from azext_iot.sdk.dps.mgmt import IotDpsClient
        from azext_iot.sdk.iothub.mgmt import IotHubClient

        self.subscription = subscription
        self.deadline = None
        self.reading_inventory = False
        self.reads = []
        reader = self
        profile = Profile(cli_ctx=get_default_cli())

        class Credential:
            def get_token(self, *_scopes, **_kwargs):
                token, _, _ = profile.get_raw_token(subscription=subscription, resource="https://management.azure.com/")
                return AccessToken(token[1], int(token[2]["expires_on"]))

        class GetOnly(RequestsTransport):
            def send(self, request, **kwargs):
                url = urlsplit(request.url)
                if (request.method != "GET" or url.scheme != "https"
                        or url.netloc != urlsplit(ARM).netloc
                        or not url.path.lower().startswith(f"/subscriptions/{subscription}/".lower())):
                    raise PhaseError("Read-only canary ARM boundary rejected a request.")
                response = super().send(request, **kwargs)
                reader.reads.append({
                    "at": utc(), "method": "GET", "host": url.netloc, "path": url.path,
                    "api_version": parse_qs(url.query).get("api-version", [None])[0],
                    "status": response.status_code,
                    "request_id": response.headers.get("x-ms-request-id"),
                    "correlation_id": response.headers.get("x-ms-correlation-request-id"),
                })
                if reader.reading_inventory and response.status_code == 200:
                    body = json.loads(response.body())
                    if not isinstance(body, dict) or not isinstance(body.get("value"), list):
                        raise PhaseError("Incomplete DPS inventory response; an empty inventory cannot be assumed.")
                return response

        def client(kind, api):
            return kind(
                Credential(), subscription, base_url=ARM, api_version=api,
                credential_scopes=["https://management.azure.com/.default"],
                transport=GetOnly(connection_timeout=5, read_timeout=20),
                retry_total=0, retry_connect=0, retry_read=0, retry_status=0, logging_enable=False,
            )
        self.dps = client(IotDpsClient, _ADR_DPS_API_VERSION)
        self.hub = client(IotHubClient, _ADR_IOT_HUB_API_VERSION)

    @staticmethod
    def snapshot(resource):
        if not isinstance(resource, dict) or not resource.get("id"):
            raise PhaseError("ARM returned an incomplete resource; inventory/cleanup is not proven.")
        return {
            "id": resource["id"], "name": resource.get("name"),
            "state": (resource.get("properties") or {}).get("provisioningState"),
            "tags": {key: (resource.get("tags") or {}).get(key) for key in ("intTest", "runUid", "kind")},
        }

    def inventory(self):
        self.reading_inventory = True
        try:
            with bounded_read(self.deadline):
                return [self.snapshot(resource) for resource in self.dps.iot_dps_resource.list_by_subscription()]
        finally:
            self.reading_inventory = False

    def get(self, record):
        from azure.core.exceptions import HttpResponseError
        with bounded_read(self.deadline):
            try:
                if record["kind"] == "hub":
                    resource = self.hub.iot_hub_resource.get(
                        resource_group_name=record["resource_group"], resource_name=record["name"])
                else:
                    resource = self.dps.iot_dps_resource.get(
                        resource_group_name=record["resource_group"], provisioning_service_name=record["name"])
            except HttpResponseError as error:
                if error.status_code == 404:
                    return None
                raise
            return self.snapshot(resource)


def capacity(inventory, required=REQUIRED_SLOTS):
    ids = [resource["id"].lower() for resource in inventory]
    if len(ids) != len(set(ids)):
        raise PhaseError("Subscription inventory contains duplicate IDs; capacity is not proven.")
    return {
        "ready": len(ids) + required <= DPS_LIMIT, "count": len(ids),
        "limit": DPS_LIMIT, "required": required, "ids": sorted(ids),
        "limit_source": "conservative DPS subscription default (no SDK quota-read operation)",
    }


def ownership(receipts, phase, uid, subscription, group, baseline):
    started = json.loads((receipts / "started.json").read_text(encoding="utf-8"))
    if not started.get("started") or started.get("run_uid") != uid or started.get("phase") != phase:
        raise PhaseError("Missing/mismatched phase-start receipt; cleanup cannot be proven.")
    records = []
    for path in sorted(receipts.glob("owned-*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        kind = record.get("kind")
        resource_type = "IotHubs" if kind == "hub" else "provisioningServices"
        expected_id = (
            f"/subscriptions/{subscription}/resourceGroups/{group}/providers/Microsoft.Devices/"
            f"{resource_type}/{record.get('name')}"
        )
        expected_uid = uid if phase == "regular" else f"{uid}-{phase}"
        if (kind not in MANIFEST["resource_kinds"](phase) or record.get("run_uid") != uid
                or record.get("phase") != phase or record.get("subscription") != subscription
                or record.get("resource_group") != group or record.get("id") != expected_id
                or record.get("tags") != {"intTest": "true", "runUid": expected_uid, "kind": kind}
                or expected_id.lower() in baseline or not record.get("create_attempted")):
            raise PhaseError("Ownership receipt does not match the isolated phase or overlaps baseline.")
        records.append(record)
        # A transient 404 after an uncertain PUT is not proof that it cannot persist later.
        confirmations = (receipts / f"created-{kind}.json", receipts / f"deleted-{kind}.json")
        record["creation_resolved"] = any(
            path.is_file() and json.loads(path.read_text(encoding="utf-8")).get("id") == expected_id
            and json.loads(path.read_text(encoding="utf-8")).get(key) is True
            for path, key in zip(confirmations, ("create_completed", "delete_completed"))
        )
    if not records or len({record["kind"] for record in records}) != len(records):
        raise PhaseError("Missing/duplicate pre-create receipts; cleanup cannot be proven.")
    return records


def recorded_ids(receipts):
    """Retain exact attempted IDs even if another receipt prevents cleanup verification."""
    result = []
    for path in receipts.glob("owned-*.json"):
        try:
            resource_id = json.loads(path.read_text(encoding="utf-8"))["id"]
            if isinstance(resource_id, str):
                result.append(resource_id)
        except (OSError, ValueError, KeyError):
            continue
    return result


def verify_cleanup(reader, records, uid, deadline, clock=time.monotonic, sleep=time.sleep):
    remaining = []
    while True:
        remaining = []
        for record in records:
            resource = reader.get(record)
            if resource is not None:
                remaining.append(resource)
        inventory = reader.inventory()
        known = {record["id"].lower() for record in records}
        remaining_ids = {resource["id"].lower() for resource in remaining}
        remaining.extend(resource for resource in inventory
                         if resource["id"].lower() in known - remaining_ids)
        unrecorded = [
            resource for resource in inventory
            if (resource.get("tags") or {}).get("runUid") in (
                uid, *(f"{uid}-{phase}" for phase in MANIFEST["PHASE_NAMES"] if phase != "regular"),
            )
            and resource["id"].lower() not in known
        ]
        if unrecorded:
            return {"complete": False, "remaining": remaining + unrecorded, "reason": "Unrecorded owned DPS IDs"}
        if not remaining:
            uncertain = [
                {"id": record["id"], "state": "404; original create outcome unresolved"}
                for record in records if not record["creation_resolved"]
            ]
            if uncertain:
                return {"complete": False, "remaining": uncertain, "reason": "Uncertain creates cannot be replayed"}
            return {"complete": True, "remaining": [], "capacity": capacity(inventory), "verified_at": utc()}
        if clock() + READ_SECONDS + 15 >= deadline:
            return {"complete": False, "remaining": remaining, "reason": "Owned resources still present at cleanup bound"}
        sleep(15)  # GET-only observation; never repeat DELETE, including alreadyDeleting resources.


def safe_junit(raw, destination, phase, selected, *, debug=None):
    if not raw.is_file():
        return {"valid": False, "reason": "Missing JUnit result"}
    try:
        cases = list(ET.parse(raw).getroot().iter("testcase"))
    except (ET.ParseError, OSError):
        return {"valid": False, "reason": "Unreadable JUnit result"}
    counts = {"tests": len(cases), "failures": 0, "errors": 0, "skipped": 0, "passed": 0}
    expected = (
        {MANIFEST["normalize_nodeid"](node) for node in debug["requestedNodes"]} if debug
        else MANIFEST["expected_nodeids"](phase)
    )
    identities = []
    output = ET.Element("testsuite", name=f"dps-{phase}")
    if debug:
        output.set("mode", "debug")
    for case in cases:
        identity = MANIFEST["junit_nodeid"](case)
        known = identity in expected
        identities.append(identity if known else "unexpected_test_identity")
        name = case.get("name") if known else "unexpected_test_identity"
        classname = case.get("classname") if known else "redacted"
        duration = case.get("time", "0")
        if not re.fullmatch(r"\d+(?:\.\d+)?", duration) or len(duration) > 32:
            duration = "0"
        clean_case = ET.SubElement(output, "testcase", name=name, classname=classname, time=duration)
        outcome = next((kind for kind in ("error", "failure", "skipped") if case.find(kind) is not None), None)
        if outcome:
            counts[{"error": "errors", "failure": "failures", "skipped": "skipped"}[outcome]] += 1
            ET.SubElement(clean_case, outcome, message="Diagnostic omitted; consult the redacted phase log.")
        else:
            counts["passed"] += 1
    for key in ("tests", "failures", "errors", "skipped"):
        output.set(key, str(counts[key]))
    ET.ElementTree(output).write(destination, encoding="utf-8", xml_declaration=True)
    os.chmod(destination, 0o600)
    counts["nodeids"] = sorted(identities)
    counts["valid"] = (
        len(cases) == selected == len(expected) and set(identities) == expected and not counts["skipped"]
    )
    return counts


def selection_count(receipts, phase, *, debug=None):
    values = [json.loads(path.read_text(encoding="utf-8")) for path in receipts.glob("selection-*.json")]
    expected = sorted(MANIFEST["normalize_nodeid"](node) for node in debug["requestedNodes"]) if debug else sorted(
        MANIFEST["expected_nodeids"](phase)
    )
    if not values or any(value.get("selected") != len(expected) or value.get("nodeids") != expected
                         or not FOCUSED["matches"](value, debug) for value in values):
        raise PhaseError("Missing/inconsistent collection receipts.")
    return len(expected)


def child(command, env, log_path, runtime, cleanup, cancelled=lambda: False):
    """Ask workers to unwind while tox/xdist's controller remains alive to await them."""
    require_linux()  # Reject before opening logs, spawning children, or accessing signal/pipe APIs.
    get_pgid = getattr(os, "getpgid", None)
    kill_pg = getattr(os, "killpg", None)
    worker_signal = getattr(signal, "SIGUSR1", None)
    kill_signal = getattr(signal, "SIGKILL", None)
    if not callable(get_pgid) or not callable(kill_pg) or worker_signal is None or kill_signal is None:
        raise PhaseError("DPS child orchestration requires POSIX process groups and signals.")
    started = time.monotonic()
    runtime_end = started + runtime
    hard_end = runtime_end + cleanup
    timed_out = interrupted = False
    buffer = b""
    discard_line = False
    redactor = Redactor()
    directory = Path(env["azext_iot_dps_phase_receipts"]) if env.get("azext_iot_dps_phase_receipts") else None
    signalled = set()
    with log_path.open("x", encoding="utf-8") as output:
        os.chmod(log_path, 0o600)
        process = subprocess.Popen(  # pylint: disable=consider-using-with
            command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
        )

        def publish(line):
            safe = redactor.line(line.decode("utf-8", errors="replace"))
            output.write(safe)
            output.flush()
            print(safe, end="", flush=True)

        try:
            eof = False
            exited_at = None
            while not eof or process.poll() is None:
                now = time.monotonic()
                if process.poll() is not None:
                    exited_at = exited_at or now
                    if now - exited_at > 2:
                        raise TimeoutError("A descendant retained the output pipe after tox exited")
                if not interrupted and (now >= runtime_end or cancelled()):
                    timed_out = now >= runtime_end
                    interrupted = True
                    hard_end = min(hard_end, now + cleanup)
                    if directory:
                        write_json(directory / "stop-requested.json", {"requested_at": utc()})
                    else:
                        process.send_signal(signal.SIGINT)
                if interrupted and directory:
                    for path in directory.glob("worker-*.json"):
                        worker = json.loads(path.read_text(encoding="utf-8"))
                        pid = worker["pid"]
                        if worker.get("ready") and pid not in signalled:
                            try:
                                if get_pgid(pid) != process.pid:
                                    raise PhaseError("Worker PID does not belong to this phase's process group.")
                                os.kill(pid, worker_signal)
                            except ProcessLookupError:
                                pass
                            signalled.add(pid)
                if now >= hard_end - READ_SECONDS:
                    raise TimeoutError("Fixture-cleanup grace expired")
                next_bound = hard_end - READ_SECONDS if interrupted else runtime_end
                readable, _, _ = select.select([process.stdout], [], [], max(.01, min(1, next_bound - now)))
                if readable:
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk:
                        eof = True
                        time.sleep(0.05)
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        if not discard_line and len(line) <= 65536:
                            publish(line + b"\n")
                        else:
                            publish(b"[oversized output line omitted]\n")
                        discard_line = False
                    if len(buffer) > 65536:
                        buffer = b""
                        discard_line = True
            if buffer and not discard_line and len(buffer) <= 65536:
                publish(buffer + b"\n")
        except (TimeoutError, KeyboardInterrupt):
            timed_out = True
        finally:
            # Known process group only; no process-name matching and no mutation retries.
            try:
                kill_pg(process.pid, signal.SIGTERM)
                time.sleep(0.2)
                kill_pg(process.pid, kill_signal)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
            process.stdout.close()
    return {
        "exit_code": process.returncode, "timed_out": timed_out,
        "interrupted": interrupted, "cleanup_deadline": min(hard_end, time.monotonic() + cleanup),
    }


def run(subscription, group, output, reader, execute=child, clock=time.monotonic, *, debug_phase=None, debug_nodes=None):
    debug = FOCUSED["select"]("DPS", debug_phase, debug_nodes)
    phases = tuple(value for value in PHASES if not debug or value[0] == debug["phase"])
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)  # A rerun must not overwrite phase evidence.
    summary_path = output.parent / "dps-phases.json"
    if summary_path.exists():
        raise PhaseError("A DPS phase summary already exists; refusing to overwrite it.")
    reserve = RUNNER_SECONDS - sum(runtime + cleanup for _, runtime, cleanup in PHASES)
    runner_seconds = sum(runtime + cleanup for _, runtime, cleanup in phases) + reserve if debug else RUNNER_SECONDS
    deadline = clock() + runner_seconds
    reader.deadline = deadline
    summary = {
        "schema": 1, "status": "failed", "subscription": subscription, "resource_group": group,
        "endpoint": ARM, "region": "centraluseuap", "started_at": utc(), "runner_seconds": runner_seconds,
        "phases": [{"name": name, "status": "blocked", "reason": "Not started",
                    **FOCUSED["provenance"](debug)} for name, _, _ in phases],
        **FOCUSED["provenance"](debug),
    }
    write_json(summary_path, summary)
    cancel = Event()
    heartbeat_stop = Event()

    def heartbeat():
        while not heartbeat_stop.wait(60):
            print(f"[DPS phases] heartbeat; {max(0, int(deadline - clock()))}s runner budget remains.", flush=True)

    previous_handlers = {sig: signal.signal(sig, lambda *_: cancel.set()) for sig in (signal.SIGINT, signal.SIGTERM)}
    thread = Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        pins = [name for name in ("azext_iot_testdps", "azext_iot_testdps_hub", "azext_iot_testhub")
                if os.environ.get(name, "").strip()]
        if pins:
            raise PhaseError("Isolated DPS phases reject supplied resource pins: " + ", ".join(pins))
        if "azext_iot_dps_coverage_file" in os.environ or any(os.environ.get(name) for name in (
            "azext_iot_dps_test_phase", "azext_iot_dps_run_uid", "azext_iot_dps_phase_receipts",
            "azext_iot_dps_junit", "azext_iot_dps_interrupt_timeout",
            "azext_iot_dps_workers",
            FOCUSED["ENV"], FOCUSED["DPS_ARGS_ENV"],
        )):
            raise PhaseError(
                "The serial runner owns phase/UID/receipt/JUnit/coverage/cleanup options; unset conflicting overrides."
            )
        if debug and any(os.environ.get(name) for name in (
            "PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
            "PYTEST_XDIST_AUTO_NUM_WORKERS", "PYTEST_XDIST_WORKER_COUNT",
        )):
            raise PhaseError("Focused DPS rejects ambient pytest selection/plugin overrides.")
        baseline = reader.inventory()
        summary["baseline"] = {"resources": baseline, "capacity": capacity(baseline), "at": utc()}
        write_json(summary_path, summary)
        baseline_ids = {resource["id"].lower() for resource in baseline}
        if not summary["baseline"]["capacity"]["ready"]:
            raise PhaseError("Initial subscription capacity cannot support three managed DPS slots.")
        records = []
        with tempfile.TemporaryDirectory(prefix="dps-phases-private-") as private:
            for index, (name, runtime, cleanup) in enumerate(phases):
                result = summary["phases"][index]
                if cancel.is_set() or clock() + runtime + cleanup + READ_SECONDS > deadline:
                    result["reason"] = "Cancelled or insufficient remaining runtime/cleanup budget"
                    break
                if index:
                    prior = summary["phases"][index - 1]
                    if not prior.get("cleanup", {}).get("complete"):
                        result["reason"] = f"{prior['name']} owned-resource cleanup was not proven"
                        break
                    previous_ids = set(prior["cleanup"]["owned_ids"])
                    present = [resource for record in records if (resource := reader.get(record)) is not None]
                    inventory = reader.inventory()
                    fresh = capacity(inventory, required=1 if name == "local-auth-toggle" else 2)
                    listed = [resource for resource in inventory
                              if resource["id"].lower() in {value.lower() for value in previous_ids}]
                    absent = not present and not listed
                    result["gate"] = {
                        "previous_owned_absent": absent, "remaining": present + listed, "capacity": fresh, "at": utc(),
                    }
                    if not absent or not fresh["ready"]:
                        result["reason"] = "Fresh owned-ID absence or subscription capacity gate failed"
                        break
                if clock() + runtime + cleanup + READ_SECONDS > deadline:
                    result["reason"] = "Read-only gates left insufficient full phase/cleanup budget"
                    break
                folder = output / name
                receipts = folder / "receipts"
                receipts.mkdir(parents=True)
                uid = uuid4().hex
                raw_junit = Path(private) / f"{name}.xml"
                environment = dict(os.environ, azext_iot_dps_test_phase=name, azext_iot_dps_run_uid=uid,
                                   azext_iot_dps_phase_receipts=str(receipts.resolve()),
                                   azext_iot_dps_test_subscription=subscription,
                                   azext_iot_dps_test_resource_group=group, azext_iot_testrg=group,
                                   azext_iot_dps_test_location="centraluseuap", azext_iot_testhub_location="centraluseuap",
                                   azext_iot_dps_workers="0" if debug or name == "local-auth-toggle" else "7",
                                   azext_iot_dps_junit=str(raw_junit))
                if debug:
                    environment[FOCUSED["ENV"]] = json.dumps(debug)
                    # DPS-int maps only this controller-managed value through tox;
                    # full phases retain checkout-wide .coverage aggregation.
                    environment["azext_iot_dps_coverage_file"] = str((folder / ".coverage").resolve())
                    # These args follow tox's base 300s dump option. Only debug
                    # disables periodic stacks; pytest/phase/cleanup deadlines stay.
                    environment[FOCUSED["DPS_ARGS_ENV"]] = shlex.join([
                        "-c", str(ROOT / "setup.cfg"), "--rootdir", str(ROOT), "--confcutdir", str(ROOT),
                        "-p", "azext_iot.tests._focused_live_plugin", "-o", "env=", "-o", "addopts=",
                        "-o", "log_cli=false", "-o", "faulthandler_timeout=0",
                        f"--cov-report=xml:{folder / 'coverage.xml'}",
                        "--capture=fd", *debug["requestedNodes"],
                    ])
                result.update(status="running", run_uid=uid, started_at=utc(),
                              runtime_seconds=runtime, cleanup_seconds=cleanup)
                result.pop("reason", None)
                write_json(summary_path, summary)
                print(f"[DPS phases] START {name}; runtime={runtime}s cleanup={cleanup}s", flush=True)
                cwd = Path.cwd()
                try:
                    os.chdir(ROOT)
                    execution = execute(
                        [sys.executable, "-m", "tox", "r", "-e", "DPS-int", "--skip-pkg-install"],
                        environment, folder / "output.log", runtime, cleanup, cancel.is_set,
                    )
                finally:
                    os.chdir(cwd)
                result.update({key: value for key, value in execution.items() if key != "cleanup_deadline"})
                records = []
                try:
                    selected = selection_count(receipts, name, debug=debug)
                    result["results"] = safe_junit(raw_junit, folder / "junit.xml", name, selected, debug=debug)
                    result["results"]["selected"] = selected
                    if debug:
                        stages = json.loads((receipts / "pytest.json").read_text(encoding="utf-8"))
                        errors = runpy.run_path(str(ROOT / "azext_iot/tests/_hub_phase_runner.py"))["phase_errors"](
                            stages, debug["requestedNodes"], "DPS", name, uid, debug=debug,
                        )
                        result["results"]["stage_errors"] = errors
                        result["results"]["valid"] = result["results"]["valid"] and not errors
                except (OSError, ValueError, KeyError, TypeError, AttributeError, PhaseError):
                    result["results"] = {"valid": False, "reason": "Missing/invalid collection or JUnit results"}
                try:
                    records = ownership(receipts, name, uid, subscription, group, baseline_ids)
                    reader.deadline = min(execution["cleanup_deadline"], deadline)
                    result["cleanup"] = verify_cleanup(
                        reader, records, uid, reader.deadline, clock=clock,
                    )
                    result["cleanup"]["owned_ids"] = [record["id"] for record in records]
                    result["cleanup"]["absent_ids"] = (
                        result["cleanup"]["owned_ids"] if result["cleanup"]["complete"] else []
                    )
                except Exception as error:  # Never print an ARM/authentication exception body.
                    result["cleanup"] = {
                        "complete": False, "error_type": type(error).__name__,
                        "reason": str(error) if isinstance(error, PhaseError) else "Cleanup verification failed",
                        "ownership_receipts": str(receipts.relative_to(output)),
                        "remaining": [{"id": resource_id, "state": "verification incomplete"}
                                      for resource_id in recorded_ids(receipts)],
                    }
                finally:
                    reader.deadline = deadline
                counts = result["results"]
                result["status"] = "passed" if (
                    result["exit_code"] == 0 and not result["timed_out"] and not result["interrupted"]
                    and counts.get("valid") and counts.get("passed", 0) > 0
                    and not counts.get("failures") and not counts.get("errors") and not counts.get("skipped")
                    and result["cleanup"].get("complete")
                ) else "failed"
                result["finished_at"] = utc()
                write_json(folder / "result.json", result)
                write_json(summary_path, summary)
                print(f"[DPS phases] END {name}: {result['status']}", flush=True)
        summary["status"] = "passed" if all(p["status"] == "passed" for p in summary["phases"]) else "failed"
    except Exception as error:  # Preserve a failed result without a credential-bearing traceback.
        summary["error"] = {
            "type": type(error).__name__,
            "message": str(error) if isinstance(error, PhaseError) else "Diagnostic omitted to protect credentials",
        }
    finally:
        if debug:
            summary["status"] = "debug-passed" if summary["status"] == "passed" else "debug-failed"
        summary["finished_at"] = utc()
        summary["arm_reads"] = getattr(reader, "reads", [])
        write_json(summary_path, summary)
        heartbeat_stop.set()
        thread.join(timeout=1)
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
    return 0 if summary["status"] == ("debug-passed" if debug else "passed") else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--region", choices=["centraluseuap"], default="centraluseuap")
    parser.add_argument("--output", default="test-result/dps-phases")
    FOCUSED["add_arguments"](parser)
    args = parser.parse_args()
    args.subscription = str(UUID(args.subscription))
    if not args.resource_group.strip():
        parser.error("--resource-group must not be empty")
    logging.getLogger("azure").setLevel(logging.ERROR)
    try:
        FOCUSED["select"]("DPS", args.debug_phase, args.debug_node)
    except ValueError as error:
        parser.error(str(error))
    try:
        require_linux()  # Public entry: no profiles, credentials, ARM reads, output writes, or children before this.
        with bounded_read():
            reader = ArmReader(args.subscription)
        return run(args.subscription, args.resource_group, args.output, reader,
                   debug_phase=args.debug_phase, debug_nodes=args.debug_node)
    except Exception as error:
        diagnostic = str(error) if isinstance(error, PhaseError) else type(error).__name__
        print(f"[DPS phases] failed before launch: {diagnostic}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
