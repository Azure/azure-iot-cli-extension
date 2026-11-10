# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Report first; delete only manifest-owned resources from finalized leaf ADO jobs."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import re
import runpy
import subprocess
import time
from urllib.parse import unquote, urljoin, urlsplit
from zipfile import BadZipFile, ZipFile

import requests
from knack.util import CLIError


ROOT = Path(__file__).resolve().parents[1]
OWNED = runpy.run_path(str(ROOT / "azext_iot/tests/_owned_resources.py"))
ADO = "https://dev.azure.com/azureiotdevxp/aziotcli/_apis/build"
GATEWAY_PATH = "/A06d21baa-2b29-46e3-8afa-c6d2a4783d6a/9c543948-e573-4146-832a-bf16b1531204/_apis/artifact/"
GRACE = timedelta(hours=6)
MAX_BYTES = 64 * 1024 * 1024
MAX_BUILDS, MAX_MANIFESTS, MAX_OWNERS, MAX_DELETES = 100, 200, 10, 50
PROFILE_SECONDS = 300
ERRORS = (ValueError, RuntimeError, OSError, KeyError, TypeError, BadZipFile, CLIError, subprocess.SubprocessError)


class Deferred(RuntimeError):
    """Keep resources when execution, ownership or the remaining budget is uncertain."""


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError("Cleanup timestamps must include their timezone.")
    return result


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def check_budget(deadline):
    if time.monotonic() >= deadline:
        raise Deferred("Profile budget exhausted; retain evidence and retry.")


def error_message(error):
    return str(error) if isinstance(error, (ValueError, RuntimeError, CLIError)) else type(error).__name__


class Ado:
    def __init__(self, token, deadline):
        if not token or token.startswith("$("):
            raise ValueError("SYSTEM_ACCESSTOKEN is required for read-only producer verification.")
        self.token, self.deadline = token, deadline
        self.session = requests.Session()

    def get(self, path, *, params=None, binary=False):
        url = ADO + path
        params = {"api-version": "7.1", **(params or {})}
        for _ in range(6):
            check_budget(self.deadline)
            parsed = urlsplit(url)
            ado = url.startswith(ADO + "/")
            gateway = (binary and parsed.hostname and parsed.hostname.endswith(".artifacts.visualstudio.com")
                       and parsed.path.startswith(GATEWAY_PATH))
            blob = parsed.hostname and parsed.hostname.endswith((
                ".vsblob.vsassets.io", ".vsblob.visualstudio.com", ".blob.core.windows.net",
            ))
            if (parsed.scheme != "https" or parsed.port not in (None, 443)
                    or parsed.username or parsed.password or parsed.fragment
                    or any(part in (".", "..") for part in unquote(parsed.path).split("/"))
                    or not (ado or gateway or binary and blob)):
                raise ValueError("Unexpected ADO artifact redirect.")
            headers = {"Authorization": "Bearer " + self.token} if ado or gateway else {}
            try:
                with self.session.get(url, params=params, headers=headers, allow_redirects=False,
                                      stream=True, timeout=(5, 25)) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        url = urljoin(url, response.headers["Location"])
                        params = None
                        continue
                    if response.status_code != 200:
                        raise RuntimeError(f"ADO read failed with HTTP {response.status_code}; no deletion authorized.")
                    chunks, size = [], 0
                    for chunk in response.iter_content(65536):
                        check_budget(self.deadline)
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise ValueError("ADO response exceeds the cleanup download limit.")
                        chunks.append(chunk)
                    data = b"".join(chunks)
                    return (data if binary else json.loads(data)), response.headers
            except requests.RequestException as error:
                # Redirect URLs can contain artifact credentials.
                raise RuntimeError(f"ADO read failed: {type(error).__name__}; no deletion authorized.") from None
        raise ValueError("ADO artifact redirect limit exceeded.")

    def json(self, path, **params):
        return self.get(path, params=params)[0]

    def builds(self, profile, build_id, now):
        if build_id:
            return [self.json(f"/builds/{build_id}")]
        result, continuation = [], None
        while len(result) < MAX_BUILDS:
            page, headers = self.get("/builds", params={
                "definitions": ",".join(map(str, profile["definitions"])),
                "queryOrder": "queueTimeDescending", "$top": MAX_BUILDS - len(result),
                "minTime": (now - timedelta(days=14)).isoformat(),
                **({"continuationToken": continuation} if continuation else {}),
            })
            result.extend(page["value"])
            continuation = headers.get("x-ms-continuationtoken")
            if not continuation:
                return result
        raise Deferred("Build discovery limit reached; select an original build ID explicitly.")

    @contextmanager
    def archive(self, build, artifact):
        content, _ = self.get(f"/builds/{build}/artifacts", binary=True, params={
            "artifactName": artifact["name"], "$format": "zip",
        })
        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if (len(entries) > 20000 or sum(item.file_size for item in entries) > 2 * MAX_BYTES
                    or len({item.filename for item in entries}) != len(entries)):
                raise ValueError("Artifact archive exceeds cleanup limits or contains duplicate paths.")
            yield archive


def document(archive, name):
    paths = [item for item in archive.namelist()
             if PurePosixPath(item).name == name and len(PurePosixPath(item).parts) <= 2]
    if len(paths) != 1:
        raise ValueError("Original ownership manifest is missing or ambiguous.")
    return json.loads(archive.read(paths[0]))


def producer(context):
    if context["product"] == "azure-iot":
        identity = context["identity"]
        return identity["build"], identity["definition"], identity["commit"]
    identity = context["producer"]
    return identity["build"], identity["pipeline"], identity["commit"]


def manifest(context, build, artifact, profile):
    OWNED["validate_context"](context)
    if (context.get("product") != profile["product"] or context["cloud"] != profile["cloud"]
            or context["subscription"].lower() != profile["subscription"].lower()
            or context["resourceGroup"].lower() not in {group.lower() for group in profile["groups"]}):
        raise ValueError("Manifest is outside the approved cleanup profile.")
    identity = producer(context)
    if identity != (str(build["id"]), str(build["definition"]["id"]), build["sourceVersion"]):
        raise ValueError("Manifest producer differs from its ADO artifact origin.")
    attempt = context.get("attempt")
    if type(attempt) is not int or attempt < 1:
        raise ValueError("An exact native job attempt is required.")
    if profile["product"] == "azure-iot":
        identity = context["identity"]
        if (identity["service"] not in ("ADU", "ADR")
                or identity["subscription"].lower() != context["subscription"].lower()
                or identity["resource_group"].lower() != context["resourceGroup"].lower()
                or identity["endpoint"] != context["endpoint"]):
            raise ValueError("Unsupported or inconsistent IoT ownership identity.")
        name = f"ownership-{identity['service']}-{identity['python']}-{identity['region']}-{attempt}"
    else:
        name = f"ops-manifest-{context['scenario']}-{attempt}"
    if artifact["name"] != name or artifact["resource"]["type"] != "PipelineArtifact":
        raise ValueError("Manifest artifact does not match the producing scenario and attempt.")


def trusted_build(build, profile):
    if (build["definition"]["id"] not in profile["definitions"]
            or build["repository"].get("type") != "GitHub"
            or build["repository"].get("id", "").lower() != profile["repository"].lower()
            or build.get("reason") == "pullRequest"
            or not build.get("sourceBranch", "").startswith(("refs/heads/", "refs/tags/"))):
        raise ValueError("Only approved leaf integration/health producers may authorize cleanup.")


def eligible(ado, build_id, artifact, context, profile, now):
    build = ado.json(f"/builds/{build_id}")
    trusted_build(build, profile)
    manifest(context, build, artifact, profile)
    if build.get("status") != "completed":
        raise Deferred("Producer run is active or its completion is unproven.")
    timeline = ado.json(f"/builds/{build_id}/timeline")
    jobs = [item for item in timeline["records"] if item["type"] == "Job"]
    if not jobs or any(item.get("state") != "completed" for item in jobs):
        raise Deferred("Producer still has unfinished jobs.")
    source = artifact.get("source", "").lower()
    matches = [item for item in jobs if item["id"].lower() == source]
    if len(matches) != 1:
        raise Deferred("Artifact source cannot be bound to a producing job.")
    job = matches[0]
    if job.get("attempt") != context["attempt"]:
        previous = [item for item in job.get("previousAttempts", []) if item["attempt"] == context["attempt"]]
        if len(previous) != 1:
            raise Deferred("Original retry-attempt timeline is unavailable.")
        previous = previous[0]
        if not re.fullmatch(r"[a-fA-F0-9-]{36}", previous["timelineId"]):
            raise ValueError("Invalid previous-attempt timeline identity.")
        timeline = ado.json(f"/builds/{build_id}/timeline/{previous['timelineId']}")
        matches = [item for item in timeline["records"] if item["type"] == "Job"
                   and item["id"].lower() == previous["recordId"].lower()
                   and item.get("attempt") == context["attempt"]]
        if len(matches) != 1:
            raise Deferred("Original retry attempt cannot be verified.")
        job = matches[0]
    finalizers = [item for item in timeline["records"] if item["type"] == "Task"
                  and item.get("parentId", "").lower() == job["id"].lower()
                  and item.get("name") == "Finalize Job" and item.get("attempt") == context["attempt"]]
    if (job.get("state") != "completed" or job.get("result") not in
            ("succeeded", "succeededWithIssues", "failed", "canceled")
            or len(finalizers) != 1 or finalizers[0].get("state") != "completed"
            or finalizers[0].get("result") != "succeeded"):
        raise Deferred("Agent finalization is unproven; a timeout or lost agent is not termination evidence.")
    finished = max(timestamp(item["finishTime"]) for item in (build, job, finalizers[0]))
    if now - finished < GRACE:
        raise Deferred("Producer has not completed the six-hour grace period.")


def recover(archive, context, destination):
    matching = []
    for name in archive.namelist():
        path = PurePosixPath(name)
        if path.name in ("ownership.json", "state.json"):
            value = json.loads(archive.read(name))
            if value.get("ownership", value) == context:
                matching.append(path.with_suffix(".events"))
    if not matching:
        raise Deferred("Final artifact lacks the original ownership context; retain the pre-published manifest.")
    target = destination / context["owner"] / "manifest.json"
    OWNED["write_new"](target, context)
    journal = OWNED["Journal"](target)
    for name in archive.namelist():
        path = PurePosixPath(name)
        if path.parent in matching:
            if not re.fullmatch(r"[0-9]{20}-[0-9a-f]{32}\.json", path.name):
                raise ValueError("Invalid ownership journal event name.")
            value = json.loads(archive.read(name))
            event = journal.directory / path.name
            if event.exists():
                if json.loads(event.read_text(encoding="utf-8")) != value:
                    raise ValueError("Conflicting journal events.")
            else:
                OWNED["write_new"](event, value)
    journal.records()
    return journal


def owner(resource):
    kind = OWNED["resource_type"](resource["id"])
    if kind == OWNED["ROLE_TYPE"]:
        match = re.match(r"cliTestOwner=([0-9a-f]{64})\n", resource.get("properties", {}).get("description") or "")
        value = match[1] if match else None
    elif kind == OWNED["DEPLOYMENT_TYPE"]:
        value = resource.get("properties", {}).get("parameters", {}).get(OWNED["PARAMETER"], {}).get("value")
    else:
        value = (resource.get("tags") or {}).get(OWNED["TAG"])
    return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) else None


def inventory(arm):
    result = {}
    for collection, api in (
            (arm.journal.group + "/resources", "2021-04-01"),
            (arm.journal.group + "/providers/Microsoft.Authorization/roleAssignments", "2022-04-01"),
            (arm.journal.group + "/providers/Microsoft.Resources/deployments", "2022-09-01")):
        for resource in arm.pages(collection, api):
            if resource["id"].lower().startswith(arm.journal.group + "/providers/"):
                result[resource["id"].lower()] = resource
    return result


def snapshot(journal, arm, resources, exclusions):
    records = journal.records()
    selected = {key: value for key, value in resources.items() if journal.owns(value)}

    def protected(resource, value):
        if (value.get("name", "").lower() in exclusions or resource in exclusions
                or any(item.startswith(resource + "/") for item in exclusions)):
            raise Deferred("An owned resource or its descendant is explicitly protected.")

    for resource, value in selected.items():
        protected(resource, value)
        if any(key.startswith(resource + "/") and owner(child) not in (None, journal.owner)
               for key, child in resources.items()):
            raise Deferred("An owned parent contains another owner's resource.")
    result = {}
    for resource in records.keys() | selected.keys():
        api = arm.api_for(resource)
        current = arm.verify(resource, api)
        pending = OWNED["pending_creates"](journal.records().get(resource, {}))
        if current is None and pending:
            if not all(OWNED["deployment_finished"](journal, arm, records[resource], creation) for creation in pending):
                raise Deferred("An unresolved creation cannot be treated as absence.")
            current = arm.verify(resource, api)
        if current is not None:
            protected(resource, current)
            if (not OWNED["creation_settled"](current)
                    or OWNED["resource_type"](resource) == OWNED["DEPLOYMENT_TYPE"]
                    and current.get("properties", {}).get("provisioningState", "").lower()
                    not in OWNED["TERMINAL_STATES"]):
                raise Deferred("Azure provisioning/deletion is still pending.")
            result[resource] = current
    return result


class GuardedArm(OWNED["Arm"]):
    def __init__(self, journal, authorize, approved, budget):
        super().__init__(journal)
        self.authorize, self.approved, self.budget = authorize, approved, budget

    def request(self, method, resource, api, body=None, headers=None, query=None):
        if method not in ("GET", "DELETE"):
            raise ValueError("Scheduled cleanup permits only reads and exact-resource deletes.")
        if method == "DELETE":
            if resource not in self.approved or self.budget["remaining"] <= 0:
                raise Deferred("Delete is outside the inspected plan or exceeds its budget.")
            self.authorize()
            expected = self.approved[resource].get("etag")
            if expected and (headers or {}).get("If-Match") != expected:
                raise Deferred("Resource changed after the cleanup plan was inspected.")
            self.budget["remaining"] -= 1
            time.sleep(1)
        return super().request(method, resource, api, body, headers, query)


def inspect_owner(ado, build, artifact, artifacts, profile, resources, output, report, budget, mode, exclusions):
    with ado.archive(build["id"], artifact) as archive:
        value = document(archive, "manifest.json" if profile["product"] == "azure-iot" else "state.json")
    context = value.get("ownership", value)
    # Other profiles can legitimately publish manifests in the same multi-region run.
    if (context.get("cloud") != profile["cloud"]
            or context.get("subscription", "").lower() != profile["subscription"].lower()
            or context.get("resourceGroup", "").lower() not in {item.lower() for item in profile["groups"]}):
        return
    manifest(context, build, artifact, profile)
    if context["owner"] not in {owner(value) for value in resources.values()}:
        return
    entry = {"owner": context["owner"], "build": build["id"], "artifact": artifact["name"], "status": "deferred"}
    report["owners"].append(entry)
    write(output / "evidence" / context["owner"] / "original.json", context)
    try:
        def authorize():
            eligible(ado, build["id"], artifact, context, profile, datetime.now(timezone.utc))

        authorize()
        final_name = artifact["name"].replace("ops-manifest-", "ops-attempt-", 1).replace("ownership-", "attempt-", 1)
        matches = [item for item in artifacts if item["name"] == final_name
                   and item.get("source") == artifact.get("source")
                   and item["resource"]["type"] == "PipelineArtifact"]
        if len(matches) != 1:
            raise Deferred("Final attempt artifact is unavailable; manual recovery is required.")
        with ado.archive(build["id"], matches[0]) as archive:
            journal = recover(archive, context, output / "evidence")
        arm = OWNED["Arm"](journal)
        arm.deadline = ado.deadline
        approved = snapshot(journal, arm, resources, exclusions)
        entry["resources"] = sorted(approved)
        entry["status"] = "eligible" if approved else "no-visible-resources"
        if mode == "delete" and approved:
            if budget["owners"] <= 0 or len(approved) > budget["remaining"]:
                raise Deferred("Delete batch limit reached; retain evidence for the next cleanup.")
            budget["owners"] -= 1
            OWNED["cleanup"](
                journal.path, timeout=max(0, ado.deadline - time.monotonic()),
                arm_factory=lambda source: GuardedArm(source, authorize, approved, budget),
            )
            entry["status"] = "absent"
    except Deferred as error:
        entry.update(status="deferred", reason=str(error))
    except ERRORS as error:
        entry.update(status="error", reason=error_message(error))
        report["errors"].append(f"Owner {context['owner']}: {error_message(error)}")


def run(profile, mode, build_id, output, exclusions, *, ado=None, deadline=None):
    deadline = time.monotonic() + PROFILE_SECONDS if deadline is None else deadline
    report = {"mode": mode, "owners": [], "resources": [], "errors": [], "limits": []}
    try:
        account = json.loads(subprocess.check_output(
            ["az", "account", "show", "--output", "json"], text=True, timeout=60,
        ))
        if account["id"].lower() != profile["subscription"].lower() or account["environmentName"] != profile["cloud"]:
            raise ValueError("Azure service connection does not match the approved profile.")
        resources = {}
        for group in profile["groups"]:
            path = output / "inventory" / group / "manifest.json"
            OWNED["create_context"](path, cloud=profile["cloud"], subscription=profile["subscription"],
                                    resourceGroup=group, product="cleanup-inventory")
            arm = OWNED["Arm"](OWNED["Journal"](path))
            arm.deadline = deadline
            resources.update(inventory(arm))
        report["resources"] = [
            {"id": key, "owner": owner(value), "status": "unmatched-owner" if owner(value) else "unowned-or-native"}
            for key, value in sorted(resources.items())
        ]
        if any(owner(value) for value in resources.values()):
            ado = ado or Ado(os.environ.get("SYSTEM_ACCESSTOKEN"), deadline)
            builds = ado.builds(profile, build_id, datetime.now(timezone.utc))
            budget, count = {"remaining": MAX_DELETES, "owners": MAX_OWNERS}, 0
            for build in builds:
                check_budget(deadline)
                trusted_build(build, profile)
                artifacts = ado.json(f"/builds/{build['id']}/artifacts")["value"]
                for artifact in artifacts:
                    prefix = "ownership-" if profile["product"] == "azure-iot" else "ops-manifest-"
                    if not artifact["name"].startswith(prefix):
                        continue
                    if count >= MAX_MANIFESTS:
                        raise Deferred("Manifest discovery limit reached; select an original build ID explicitly.")
                    count += 1
                    inspect_owner(ado, build, artifact, artifacts, profile, resources, output, report,
                                  budget, mode, exclusions)
    except Deferred as error:
        report["limits"].append(str(error))
    except ERRORS as error:
        report["errors"].append(error_message(error))
    finally:
        outcomes = {entry["owner"]: entry["status"] for entry in report["owners"]}
        for resource in report["resources"]:
            resource["status"] = outcomes.get(resource["owner"], resource["status"])
        write(output / "report.json", report)
    print(json.dumps({key: len(report[key]) for key in ("owners", "resources", "errors", "limits")}))
    if report["limits"]:
        print("##vso[task.logissue type=warning]Cleanup was bounded; inspect the retained report for deferred work.")
    if report["errors"]:
        raise RuntimeError("Cleanup is incomplete; inspect the report and retain ownership evidence.")
    return report


def main():
    profiles = json.loads((ROOT / ".azure-devops/cleanup-profiles.json").read_text(encoding="utf-8"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, choices=profiles)
    parser.add_argument("--mode", choices=("report", "delete"), default="report")
    parser.add_argument("--build-id", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.build_id < 0:
        parser.error("Build ID must be zero or a positive original producer ID.")
    exclusions = os.environ.get("EXCLUSIONS", "")
    if exclusions.startswith("$("):
        exclusions = ""
    run(profiles[args.profile], args.mode, args.build_id, args.output / args.profile,
        {value.lower() for value in exclusions.split()})


if __name__ == "__main__":
    main()
