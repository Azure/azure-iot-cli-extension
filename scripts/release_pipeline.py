# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Release orchestration with immutable candidates and explicit external publication."""

import argparse
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from email.parser import Parser
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import signal
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zipfile


REPOSITORY = "Azure/azure-iot-cli-extension"
INDEX_REPOSITORY = "Azure/azure-cli-extensions"
ADO = "https://dev.azure.com/azureiotdevxp/aziotcli/_apis"
FEED = "https://pkgs.dev.azure.com/azureiotdevxp/aziotcli/_packaging/pip/pypi/simple/"
BRANCHES = {"dev", "preview", "release/1.1.0-preview"}
INTEGRATION_PARAMETERS = {
    "mode": "Integration tests", "services": ["DPS/Hub/ADR/ADU"],
    "pythonVersions": ["3.10", "3.13"], "regions": "australiaeast", "armEndpoint": "public",
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def environment(name):
    value = os.environ.get(name, "").strip()
    if not value or "$(" in value or "\n" in value or "\r" in value:
        raise ValueError(f"Configure {name} explicitly; unresolved pipeline variables are not allowed.")
    return value


def identifier(value):
    if not re.fullmatch(r"[1-9][0-9]*", str(value)):
        raise ValueError("Expected a positive build or pipeline ID.")
    return str(value)


def commit(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("Expected an immutable, lowercase 40-character commit SHA.")
    return value


def branch(value):
    value = value.removeprefix("refs/heads/")
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]*", value) or value.startswith("refs/")
            or any(part in value for part in ("..", "//", "@{"))
            or value.endswith(("/", ".", ".lock"))):
        raise ValueError("Source must be a safe branch name, not a tag or revision expression.")
    return f"refs/heads/{value}"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def command(args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def api(url, token, method="GET", data=None, missing=False, content_type="application/json"):
    if not url.startswith((ADO + "/", "https://api.github.com/", "https://uploads.github.com/")):
        raise ValueError("Unapproved API destination.")
    payload = data if isinstance(data, bytes) else json.dumps(data).encode() if data is not None else None
    request = Request(url, data=payload, method=method, headers={
        "Authorization": f"Bearer {token}", "Content-Type": content_type,
        "Accept": "application/json", "User-Agent": "azure-iot-release",
    })
    try:
        with build_opener(NoRedirect()).open(request, timeout=60) as response:
            result = response.read()
            return json.loads(result) if result else None
    except HTTPError as error:
        if missing and error.code == 404:
            return None
        raise RuntimeError(f"{method} API request failed with HTTP {error.code}; no automatic write retry.") from None


def ado(resource, **kwargs):
    separator = "&" if "?" in resource else "?"
    return api(f"{ADO}/{resource}{separator}api-version=7.1", environment("SYSTEM_ACCESSTOKEN"), **kwargs)


def github(resource, **kwargs):
    return api(f"https://api.github.com/{resource}", environment("RELEASE_GITHUB_TOKEN"), **kwargs)


def checkout(destination, resolving=False):
    if resolving:
        if environment("RELEASE_MODE") == "Release":
            automation_allowed()
    source_branch = branch(environment("RELEASE_SOURCE_BRANCH"))
    source_commit = None if resolving else commit(environment("RELEASE_SOURCE_COMMIT"))
    if destination.exists():
        raise ValueError("The source destination must be a new, isolated directory.")
    subprocess.run(["git", "init", "--quiet", str(destination)], check=True)
    subprocess.run(["git", "remote", "add", "origin", f"https://github.com/{REPOSITORY}.git"],
                   cwd=destination, check=True)
    fetch = ["git", "fetch", "--quiet", "--filter=blob:none", "--depth=1", "origin"]
    subprocess.run(fetch + [source_branch if resolving else source_commit], cwd=destination, check=True)
    tip = commit(command(["git", "rev-parse", "FETCH_HEAD"], destination))
    selected = source_commit or tip
    subprocess.run(["git", "checkout", "--quiet", "--detach", selected], cwd=destination, check=True)
    if command(["git", "rev-parse", "HEAD"], destination) != selected:
        raise ValueError("Source checkout did not match the resolved commit.")
    if resolving:
        for relative in (
            ".azure-devops/templates/integration-service.yml", "azext_iot/tests/_ado_pipeline.py",
            "scripts/check_index_compatibility.py", "scripts/select-openssl.sh",
        ):
            if not (destination / relative).is_file():
                raise ValueError(f"Source branch needs the migration/index-check prerequisites: {relative}")
        integration = (destination / ".azure-devops/integration_tests.yml").read_text(encoding="utf-8")
        if "releaseBuildId" not in integration:
            raise ValueError("The selected source does not support pipeline 147's release-candidate handoff.")
        print(f"##vso[task.setvariable variable=commit;isOutput=true]{selected}", flush=True)
    return selected


def wheel_metadata(path):
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(names) != 1 or archive.getinfo(names[0]).file_size > 1024 * 1024:
            raise ValueError("Expected one bounded wheel METADATA document.")
        value = Parser().parsestr(archive.read(names[0]).decode("utf-8"))
        if value.get("Name", "").lower().replace("_", "-") != "azure-iot":
            raise ValueError("Only the azure-iot distribution may be released.")
        version = value.get("Version", "")
        if not re.fullmatch(r"[0-9][A-Za-z0-9.+!]*", version):
            raise ValueError("Wheel version is missing or unsafe.")
        if "azext_iot/__init__.py" not in archive.namelist():
            raise ValueError("Wheel does not contain the IoT extension.")
    return version


def producer():
    return {
        "definition": identifier(environment("SYSTEM_DEFINITIONID")),
        "build": identifier(environment("BUILD_BUILDID")),
        "commit": commit(environment("BUILD_SOURCEVERSION")),
    }


def feed_environment():
    authenticated = os.environ.get("PIP_INDEX_URL", "")
    try:
        uri = urlsplit(authenticated)
        port = uri.port
    except ValueError:
        raise ValueError("PipAuthenticate did not provide a valid authenticated feed URL.") from None
    expected = urlsplit(FEED)
    if (uri.scheme != expected.scheme or uri.hostname != expected.hostname
            or uri.path.rstrip("/") != expected.path.rstrip("/")
            or not uri.username or not uri.password or port not in (None, 443)
            or uri.query or uri.fragment or any(char.isspace() for char in authenticated)):
        raise ValueError("PipAuthenticate must authenticate exactly the configured aziotcli/pip feed.")
    result = {key: value for key, value in os.environ.items() if not key.startswith("PIP_")}
    result.update(
        PIP_INDEX_URL=authenticated, PIP_CONFIG_FILE=os.devnull, PIP_EXTRA_INDEX_URL="",
        PIP_KEYRING_PROVIDER="disabled", PIP_NO_INPUT="1", PIP_DISABLE_PIP_VERSION_CHECK="1",
        PIP_NO_CACHE_DIR="1",
    )
    return result


def configure_feed():
    configured = feed_environment()
    for key in sorted(set(os.environ) | set(configured)):
        if key.startswith("PIP_") and key != "PIP_INDEX_URL":
            if not re.fullmatch(r"PIP_[A-Z0-9_]+", key):
                raise ValueError("Invalid inherited pip configuration variable name.")
            print(f"##vso[task.setvariable variable={key}]{configured.get(key, '')}", flush=True)
    print("Using only the authenticated aziotcli/pip feed; alternate indexes and pip configuration are disabled.")


def unit_dependencies(source, directory, check=False):
    venv = source / ".tox/python-azcur-unit"
    python = str(venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    env = feed_environment()
    if not check:
        subprocess.run([python, "-m", "pip", "check"], env=env, check=True)
        constraints = subprocess.check_output([
            python, "-c",
            "from importlib.metadata import requires\nfrom packaging.requirements import Requirement\n"
            "for name in ('azure-cli', 'azure-cli-core'):\n"
            "    for value in requires(name):\n"
            "        requirement = Requirement(value)\n"
            "        requirement.extras.clear()\n"
            "        print(requirement)\n",
        ], env=env, text=True)
        directory.mkdir(parents=True, exist_ok=False)
        path = directory / "cli-constraints.txt"
        path.write_text(constraints, encoding="utf-8")
        print(f"##vso[task.setvariable variable=PIP_CONSTRAINT]{path.resolve()}", flush=True)
        return
    site = Path(subprocess.check_output(
        [python, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"], text=True).strip())
    target = site / "azure-cli-extensions/azure-iot"
    if not target.is_dir():
        raise ValueError("The tested extension dependency directory is missing.")
    env["PYTHONPATH"] = str(target)
    subprocess.run([python, "-m", "pip", "check"], env=env, check=True)
    requirements = subprocess.check_output(
        [python, "-m", "pip", "freeze", "--path", str(target)], env=env, text=True)
    if not re.search(r"(?m)^azure-iot(?:==| @ )", requirements):
        raise ValueError("The tested extension is missing from its dependency inventory.")
    (directory / "requirements.txt").write_text(requirements, encoding="utf-8")


def build_candidate(source, work_dir, inventory=None):
    build_env = feed_environment()

    def run(args):
        subprocess.run(args, cwd=source, env=build_env, check=True)

    run([sys.executable, "-m", "pip", "install", "-r", "dev_requirements"])
    run([sys.executable, "-m", "build", "--wheel"])
    wheels = list((source / "dist").glob("*.whl"))
    if len(wheels) != 1:
        raise ValueError("Build must produce exactly one wheel.")
    runtime_sbom(wheels[0], work_dir, inventory or work_dir / "runtime-inventory")


def runtime_sbom(wheel, work_dir, inventory):
    build_env = feed_environment()

    def run(args):
        subprocess.run(args, cwd=wheel.parent, env=build_env, check=True)

    venv = work_dir / "sbom-venv"
    run([sys.executable, "-m", "venv", str(venv)])
    python = str(venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    run([python, "-m", "pip", "install", str(wheel)])
    run([python, "-m", "pip", "check"])
    inventory.mkdir(parents=True, exist_ok=False)
    requirements = inventory / "requirements.txt"
    requirements.write_text(subprocess.check_output(
        [python, "-m", "pip", "freeze"], env=build_env, text=True), encoding="utf-8")
    platform = "win-x64.exe" if os.name == "nt" else "linux-x64"
    tool = work_dir / ("sbom-tool.exe" if os.name == "nt" else "sbom-tool")
    subprocess.run([
        "curl", "--fail", "--location", "--proto", "=https", "--tlsv1.2",
        f"https://github.com/microsoft/sbom-tool/releases/download/v4.1.5/sbom-tool-{platform}",
        "--output", str(tool),
    ], check=True)
    expected = ("625767b371b7fdd58f40f618b8a86da0247a33c89e419039c86b4edba1dad4b5" if os.name == "nt"
                else "bf5d4f99bc98c119d549d08fc02ae92598a7a42772f17317c01031a92632e05b")
    if digest(tool) != expected:
        raise ValueError("SBOM tool digest does not match the pinned release.")
    tool.chmod(0o700)
    run([str(tool), "generate", "-b", str(wheel.parent), "-bc", str(inventory), "-pn", "Azure IoT CLI Extension",
         "-pv", wheel_metadata(wheel), "-ps", "Microsoft"])


def runtime_receipt(source, directory, inventory):
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name

    selected = commit(environment("RELEASE_SOURCE_COMMIT"))
    if command(["git", "rev-parse", "HEAD"], source) != selected:
        raise ValueError("Runtime inventory source differs from the selected commit.")
    wheels = list(directory.glob("*.whl"))
    if len(wheels) != 1:
        raise ValueError("Runtime inventory requires exactly one wheel.")
    manifest = read(directory / "_manifest/spdx_2.2/manifest.spdx.json")
    packages = {(canonicalize_name(p["name"]), p.get("versionInfo")) for p in manifest["packages"]}
    expected = set()
    for line in (inventory / "requirements.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        requirement = Requirement(line)
        if requirement.url:
            if canonicalize_name(requirement.name) != "azure-iot":
                raise ValueError("Unexpected direct-URL runtime dependency.")
            continue
        pins = list(requirement.specifier)
        if len(pins) != 1 or pins[0].operator != "==":
            raise ValueError("Runtime dependency inventory must contain exact installed versions.")
        expected.add((canonicalize_name(requirement.name), pins[0].version))
    if not expected or not expected.issubset(packages):
        raise ValueError("SBOM omitted installed runtime dependencies.")
    package_ids = {p["SPDXID"] for p in manifest["packages"] if p["SPDXID"] != "SPDXRef-RootPackage"}
    if not any(r["relationshipType"] == "DEPENDS_ON" and r["spdxElementId"] in package_ids
               and r["relatedSpdxElement"] in package_ids for r in manifest["relationships"]):
        raise ValueError("SBOM has no resolved dependency graph; source-only fallback is not sufficient.")
    write(directory / "_manifest/runtime-provenance.json", {
        "sourceCommit": selected, "platform": sys.platform,
        "pythonVersion": ".".join(str(value) for value in sys.version_info[:3]),
        "wheel": {"file": wheels[0].name, "sha256": digest(wheels[0])},
        "manifestSha256": digest(directory / "_manifest/spdx_2.2/manifest.spdx.json"),
    })


def verify_runtime(directory, platform):
    value = read(directory / "_manifest/runtime-provenance.json")
    wheel = value["wheel"]
    if (value["sourceCommit"] != commit(environment("RELEASE_SOURCE_COMMIT"))
            or value["platform"] != platform or Path(wheel["file"]).name != wheel["file"]
            or not re.fullmatch(r"azure_iot-[A-Za-z0-9_.+!-]+\.whl", wheel["file"])
            or digest(directory / wheel["file"]) != wheel["sha256"]
            or digest(directory / "_manifest/spdx_2.2/manifest.spdx.json") != value["manifestSha256"]):
        raise ValueError("Runtime SBOM provenance or asset digest mismatch.")
    return value


def windows_runtime(source, directory, work_dir, inventory):
    if sys.platform != "win32":
        raise ValueError("Windows runtime dependencies must be resolved on Windows.")
    value = verify_runtime(directory, "linux")
    output = work_dir / "windows-runtime"
    output.mkdir(parents=True, exist_ok=False)
    wheel = output / value["wheel"]["file"]
    shutil.copyfile(directory / wheel.name, wheel)
    runtime_sbom(wheel, work_dir, inventory)
    runtime_receipt(source, output, inventory)


def assemble_runtime(source, directory):
    linux = directory / "release-runtime-linux"
    windows = directory / "release-runtime-windows"
    left = verify_runtime(linux, "linux")
    right = verify_runtime(windows, "win32")
    if left["wheel"] != right["wheel"]:
        raise ValueError("Both platform SBOMs must describe the exact same wheel.")
    output = source / "dist"
    shutil.copytree(linux, output)
    shutil.copytree(windows / "_manifest", output / "_manifest/windows")


def create_candidate(source, directory):
    wheels = list((source / "dist").glob("*.whl"))
    if len(wheels) != 1:
        raise ValueError("Build must produce exactly one wheel.")
    wheel = wheels[0]
    source_commit = commit(environment("RELEASE_SOURCE_COMMIT"))
    if command(["git", "rev-parse", "HEAD"], source) != source_commit:
        raise ValueError("Build checkout no longer matches the selected source.")
    subprocess.run(["git", "diff", "--exit-code", "HEAD"], cwd=source, check=True)
    manifests = list((source / "dist/_manifest").rglob("*.spdx.json"))
    if not manifests:
        raise ValueError("SBOM generation did not produce an SPDX manifest.")
    directory.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(wheel, directory / wheel.name)
    with zipfile.ZipFile(directory / "SBOM.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((source / "dist/_manifest").rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source / "dist"))
    value = {
        "schema": 1, "repository": REPOSITORY,
        "sourceBranch": branch(environment("RELEASE_SOURCE_BRANCH")), "sourceCommit": source_commit,
        "producer": producer(),
        "cohorts": integration_cohorts(),
        "wheel": {"file": wheel.name, "sha256": digest(wheel), "version": wheel_metadata(wheel)},
        "sbom": {"file": "SBOM.zip", "sha256": digest(directory / "SBOM.zip")},
    }
    write(directory / "candidate.json", value)
    verify_candidate(directory)
    print("##vso[task.setvariable variable=matrix;isOutput=true]" + json.dumps({
        key: {"cohort": key} for key in value["cohorts"]
    }), flush=True)
    return value


def verify_candidate(directory):
    value = read(directory / "candidate.json")
    if (type(value["schema"]) is not int or value["schema"] != 1 or value["repository"] != REPOSITORY
            or value["producer"] != producer()
            or value["sourceBranch"] != branch(environment("RELEASE_SOURCE_BRANCH"))
            or value["sourceCommit"] != commit(environment("RELEASE_SOURCE_COMMIT"))):
        raise ValueError("Candidate provenance does not match this release run and source.")
    if value.get("cohorts") != integration_cohorts():
        raise ValueError("Candidate cohort inventory does not match the complete requested qualification.")
    wheel = value["wheel"]
    if not re.fullmatch(r"azure_iot-[A-Za-z0-9_.+!-]+\.whl", wheel["file"]):
        raise ValueError("Unsafe candidate wheel name.")
    governance = directory / "_manifest"
    if governance.exists() or governance.is_symlink():
        if (governance.is_symlink() or not governance.is_dir() or any(
                path.is_symlink() or path.suffix.lower() == ".whl" or not (path.is_file() or path.is_dir())
                for path in governance.rglob("*"))):
            raise ValueError("Unsafe governed artifact metadata.")
    files = [path for path in directory.iterdir() if path.name != "_manifest"]
    if (directory.is_symlink() or {path.name for path in files} != {wheel["file"], "candidate.json", "SBOM.zip"}
            or any(path.is_symlink() or not path.is_file() for path in files)):
        raise ValueError("Expected only the three declared candidate assets as regular files.")
    for item in (wheel, value["sbom"]):
        if Path(item["file"]).name != item["file"] or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise ValueError("Invalid candidate asset identity.")
        if digest(directory / item["file"]) != item["sha256"]:
            raise ValueError("Candidate asset digest mismatch.")
    if value["sbom"]["file"] != "SBOM.zip" or wheel_metadata(directory / wheel["file"]) != wheel["version"]:
        raise ValueError("Candidate metadata mismatch.")
    return value


def integration_cohorts(target=None):
    target = target or environment("RELEASE_DPS_TARGET")
    public = deepcopy(INTEGRATION_PARAMETERS)
    if target == "public":
        return {"public": public}
    if target != "canary":
        raise ValueError("DPS target must be public or canary.")
    dps = {**deepcopy(public), "services": ["DPS"], "regions": "centraluseuap", "armEndpoint": "canary"}
    public["services"] = ["HubControl", "HubData", "ADU", "ADR"]
    return {"dps_canary": dps, "public": public}


def integration_parameters(candidate, cohort=None):
    key = cohort or environment("RELEASE_COHORT")
    return dict(candidate["cohorts"][key], releaseBuildId=candidate["producer"]["build"])


def validate_integration(build, candidate, cohort=None):
    parameters = build.get("templateParameters")
    if isinstance(parameters, str):
        parameters = json.loads(parameters)
    parameters = dict(parameters)
    for key in ("services", "pythonVersions"):
        if isinstance(parameters.get(key), str):
            parameters[key] = json.loads(parameters[key])
    parameters["releaseBuildId"] = identifier(parameters.get("releaseBuildId"))
    expected = integration_parameters(candidate, cohort)
    repository = build["repository"]
    if (build["definition"]["id"] != 147 or repository.get("id") != REPOSITORY
            or repository.get("type") != "GitHub" or repository.get("name") not in (None, REPOSITORY)
            or build["project"]["id"].lower() != environment("SYSTEM_TEAMPROJECTID").lower()
            or build["sourceVersion"] != candidate["sourceCommit"]
            or build["sourceBranch"] != candidate["sourceBranch"] or parameters != expected):
        raise ValueError("Pipeline 147 run does not match the exact release qualification request.")


def existing_integration(candidate) -> dict | None:
    parent = ado(f"build/builds/{candidate['producer']['build']}")
    if (str(parent["definition"]["id"]) != candidate["producer"]["definition"]
            or parent["sourceVersion"] != candidate["producer"]["commit"]):
        raise ValueError("Release producer metadata mismatch.")
    query = urlencode({
        "definitions": 147, "branchName": candidate["sourceBranch"], "minTime": parent["queueTime"],
        "queryOrder": "queueTimeAscending", "$top": 1000,
    })
    builds = ado("build/builds?" + query)["value"]
    if len(builds) >= 1000:
        raise ValueError("Too many child builds to prove unique ownership; inspect pipeline 147 before retrying.")
    matches = {key: [] for key in candidate["cohorts"]}
    for build in builds:
        parameters = build.get("templateParameters", {})
        if isinstance(parameters, str):
            parameters = json.loads(parameters)
        if str(parameters.get("releaseBuildId", "")) == candidate["producer"]["build"]:
            scopes = []
            for key in candidate["cohorts"]:
                try:
                    validate_integration(build, candidate, key)
                    scopes.append(key)
                except ValueError:
                    continue
            if len(scopes) != 1:
                raise ValueError("An owned child has an unexpected release cohort or source.")
            matches[scopes[0]].append(build)
    if any(len(builds) > 1 for builds in matches.values()):
        raise ValueError("Multiple children reference this release; resolve the duplicate cohorts before proceeding.")
    selected = matches[environment("RELEASE_COHORT")]
    return selected[0] if selected else None


def cancel_integration(record, directory):
    candidate = verify_candidate(directory)
    if not record.exists():
        existing = existing_integration(candidate)
        if existing is None:
            print("No child of this release was found; no cancellation request was sent.", flush=True)
            return
        run = {"id": identifier(existing.get("id")), "producer": candidate["producer"],
               "cohort": environment("RELEASE_COHORT")}
    else:
        run = read(record)
    if run["producer"] != candidate["producer"] or run["cohort"] != environment("RELEASE_COHORT"):
        raise ValueError("Refusing to cancel a child owned by another release.")
    build = ado(f"build/builds/{identifier(run['id'])}")
    validate_integration(build, candidate)
    if build["status"] != "completed":
        ado(f"build/builds/{run['id']}", method="PATCH", data={"status": "cancelling"})
        print(f"Requested cancellation of pipeline 147 build {run['id']}.", flush=True)


def safe_queue_delay(now=None):
    now = now or datetime.now(timezone.utc)
    cleanup = now.replace(hour=13, minute=0, second=0, microsecond=0)
    if cleanup <= now < cleanup + timedelta(minutes=30):
        return (cleanup + timedelta(minutes=30) - now).total_seconds()
    if cleanup <= now:
        cleanup += timedelta(days=1)
    if cleanup - now < timedelta(hours=8):
        return (cleanup + timedelta(minutes=30) - now).total_seconds()
    return 0


def admit_integration():
    deadline = time.monotonic() + 9 * 3600
    query = urlencode({
        "definitions": "109,147,166", "statusFilter": "inProgress,notStarted,postponed,cancelling", "$top": 100,
    })
    while True:
        delay = safe_queue_delay()
        if not delay and not ado("build/builds?" + query)["value"]:
            return
        if time.monotonic() >= deadline:
            raise TimeoutError("No safe IoT integration window within nine hours; no child was queued.")
        print("Waiting without Azure resources for cleanup headroom and an idle IoT pipeline family.", flush=True)
        time.sleep(min(60, delay or 60))


def integrate(directory, record, timeout=25200):
    candidate = verify_candidate(directory)
    payload = {
        "definition": {"id": 147}, "sourceBranch": candidate["sourceBranch"],
        "sourceVersion": candidate["sourceCommit"],
        "templateParameters": {
            key: value if isinstance(value, str) else json.dumps(value)
            for key, value in integration_parameters(candidate).items()
        },
    }
    run = existing_integration(candidate)
    if run is None:
        if int(os.environ.get("SYSTEM_JOBATTEMPT", "1")) != 1:
            raise ValueError("No child found on a retried job; do not risk requeuing an uncertain prior request.")
        admit_integration()
        run = ado("build/builds", method="POST", data=payload)
    run_id = identifier(run["id"])
    write(record, {"id": run_id, "producer": candidate["producer"], "cohort": environment("RELEASE_COHORT")})
    print(f"##vso[task.setvariable variable=integrationBuildId]{run_id}", flush=True)
    print(f"Integration: https://dev.azure.com/azureiotdevxp/aziotcli/_build/results?buildId={run_id}", flush=True)

    def interrupted(_signum, _frame):
        cancel_integration(record, directory)
        raise SystemExit(130)

    previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGINT)}
    deadline = time.monotonic() + timeout
    try:
        while True:
            build = ado(f"build/builds/{run_id}")
            validate_integration(build, candidate)
            if build["status"] == "completed":
                if build["result"] != "succeeded":
                    raise RuntimeError(f"Pipeline 147 build {run_id} finished with {build['result']}.")
                return run_id
            if time.monotonic() >= deadline:
                cancel_integration(record, directory)
                raise TimeoutError(f"Pipeline 147 build {run_id} exceeded the release wait budget.")
            time.sleep(30)
    except (ValueError, RuntimeError, OSError, KeyError):
        cancel_integration(record, directory)
        raise
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def verify_integration_artifacts(directory, artifacts):
    candidate = verify_candidate(directory)
    wheels = list(artifacts.glob("integration-wheel-*/*.whl"))
    if not wheels or any(digest(path) != candidate["wheel"]["sha256"] for path in wheels):
        raise ValueError("Integration did not retain the exact release candidate wheel.")
    manifests = list(artifacts.glob("integration-wheel-*/candidate.json"))
    if ({path.parent for path in manifests} != {path.parent for path in wheels}
            or any(read(path) != candidate for path in manifests)):
        raise ValueError("Integration candidate provenance is missing or differs from the release.")
    sboms = list(artifacts.glob("integration-wheel-*/SBOM.zip"))
    if ({path.parent for path in sboms} != {path.parent for path in wheels}
            or any(digest(path) != candidate["sbom"]["sha256"] for path in sboms)):
        raise ValueError("Integration did not retain the exact release candidate SBOM.")


def automation_allowed():
    if branch(environment("RELEASE_SOURCE_BRANCH")).removeprefix("refs/heads/") not in BRANCHES:
        raise ValueError("Publication requires an approved protected source branch.")
    if environment("BUILD_SOURCEBRANCH") != "refs/heads/dev":
        raise ValueError("Publication requires the reviewed release automation on dev, not a feature branch.")
    if environment("BUILD_REPOSITORY_NAME") != REPOSITORY:
        raise ValueError("Publication is only allowed from the upstream repository.")


def release_options():
    mode = environment("RELEASE_MODE")
    index = os.environ.get("RELEASE_CREATE_INDEX_PR", "false").lower()
    if mode not in {"Plan", "Validate", "Release"} or index not in {"true", "false"}:
        raise ValueError("Invalid release mode or createIndexPr option.")
    if index == "true" and mode != "Release":
        raise ValueError("createIndexPr requires Release mode and a public GitHub release.")
    return mode, index == "true"


def publication_allowed():
    if release_options()[0] != "Release":
        raise ValueError("Publication requires explicit Release mode.")
    automation_allowed()
    environment("RELEASE_GITHUB_TOKEN")


def index_check(source, directory, work_dir):
    candidate = verify_candidate(directory)
    wheels = list((work_dir / "wheels").glob("*.whl"))
    if len(wheels) != 1 or digest(wheels[0]) != candidate["wheel"]["sha256"]:
        raise ValueError("Index compatibility must check the immutable release candidate.")
    checker = runpy.run_path(str(source / "scripts/check_index_compatibility.py"))
    code = checker["check"](work_dir, source)
    report = read(work_dir / "reports/report.json")
    (work_dir / "reports/summary.md").write_text(
        "# Required release index compatibility\n\n"
        "HIGH findings, tool failures and incomplete checks block integration and publication. "
        "MEDIUM-only findings remain warnings, matching index CI.\n\n"
        f"Result: {report['result']}\n\n"
        f"Wheel SHA-256: `{candidate['wheel']['sha256']}`\n\n"
        "See report.json and linter.log for the complete findings and toolchain provenance.\n",
        encoding="utf-8",
    )
    if code or report.get("error") or not report["result"].startswith("Passed"):
        raise RuntimeError("Required index compatibility failed; inspect its report and linter log.")


def tag_commit(tag):
    value = github(f"repos/{REPOSITORY}/git/ref/tags/{quote(tag, safe='')}", missing=True)
    if value is None:
        return None
    obj = value["object"]
    for _ in range(5):
        if obj["type"] == "commit":
            return commit(obj["sha"])
        if obj["type"] != "tag":
            break
        obj = github(f"repos/{REPOSITORY}/git/tags/{obj['sha']}")["object"]
    raise ValueError("Release tag does not resolve to a commit.")


def find_release(tag):
    value = github(f"repos/{REPOSITORY}/releases/tags/{quote(tag, safe='')}", missing=True)
    if value is not None:
        return value
    page = 1
    while True:
        values = github(f"repos/{REPOSITORY}/releases?per_page=100&page={page}")
        matches = [item for item in values if item["tag_name"] == tag]
        if len(matches) > 1:
            raise ValueError("Multiple drafts exist for the same version.")
        if matches:
            return matches[0]
        if len(values) < 100:
            return None
        page += 1


def verify_public_assets(release, candidate):
    if release["draft"]:
        raise ValueError("The qualified release is not public.")
    for asset in (candidate["wheel"], candidate["sbom"]):
        matches = [item for item in release["assets"] if item["name"] == asset["file"]]
        if len(matches) != 1 or matches[0].get("digest") != "sha256:" + asset["sha256"]:
            raise ValueError("Public release assets do not match the qualified candidate.")


def github_contents(repository, ref):
    contents = github(f"repos/{repository}/contents/src/index.json?" + urlencode({"ref": ref}))
    if contents.get("encoding") != "base64":
        contents = github(f"repos/{repository}/git/blobs/{contents['sha']}")
    if contents.get("encoding") != "base64":
        raise ValueError("GitHub did not return base64 index content.")
    return base64.b64decode(contents["content"], validate=False)


def verify_index_change(before, after, entry):
    prior = before["extensions"]["azure-iot"]
    normalized = json.loads(json.dumps(after))
    normalized["extensions"]["azure-iot"] = prior
    if (normalized != before or after["extensions"]["azure-iot"] != prior + [entry]):
        raise ValueError("Index update changed more than the verified candidate entry.")


def verify_existing_index_branch(fork, ref, contents, entry):
    comparison = github(
        f"repos/{INDEX_REPOSITORY}/compare/main...{quote(fork.split('/')[0] + ':' + ref, safe='')}")
    commits = comparison.get("commits", [])
    if (len(commits) != 1 or comparison.get("ahead_by") != 1
            or [item["filename"] for item in comparison.get("files", [])] != ["src/index.json"]
            or len(commits[0]["parents"]) != 1
            or commits[0]["parents"][0]["sha"] != comparison["merge_base_commit"]["sha"]):
        raise ValueError("Existing index branch has unrelated commits or files; refusing to overwrite it.")
    before = json.loads(github_contents(INDEX_REPOSITORY, comparison["merge_base_commit"]["sha"]))
    verify_index_change(before, json.loads(contents), entry)


def index_metadata(wheel, destination):
    if Path(environment("VIRTUAL_ENV")).resolve() != Path(sys.prefix).resolve():
        raise ValueError("Index metadata generation requires the activated tooling virtual environment.")
    from importlib.metadata import version
    from azdev.operations.extensions.util import get_ext_metadata

    if version("azdev") != "0.2.13":
        raise ValueError("Index metadata generation requires azdev 0.2.13.")
    destination.mkdir(parents=True, exist_ok=False)
    return get_ext_metadata(str(destination), str(wheel), "azure-iot")


def prepare_publication(directory, tooling, work_dir):
    from packaging.version import Version

    candidate = verify_candidate(directory)
    version = Version(candidate["wheel"]["version"])
    if str(version) != candidate["wheel"]["version"]:
        raise ValueError("The wheel version must already be normalized.")
    wheel = candidate["wheel"]
    entry = {
        "downloadUrl": f"https://github.com/{REPOSITORY}/releases/download/v{version}/{wheel['file']}",
        "sha256Digest": wheel["sha256"], "filename": wheel["file"],
        "metadata": index_metadata(directory / wheel["file"], work_dir / "index-metadata"),
    }
    tooling.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(Path(__file__), tooling / "release_pipeline.py")
    prepared = tooling / "publication.json"
    write(prepared, {"candidate": candidate, "indexEntry": entry, "prerelease": version.is_prerelease})
    verify_publication_inputs(directory, prepared)


def verify_publication_inputs(directory, prepared):
    candidate = verify_candidate(directory)
    value = read(prepared)
    entry = value["indexEntry"]
    wheel = candidate["wheel"]
    expected_url = f"https://github.com/{REPOSITORY}/releases/download/v{wheel['version']}/{wheel['file']}"
    if (value["candidate"] != candidate or type(value["prerelease"]) is not bool
            or set(entry) != {"downloadUrl", "sha256Digest", "filename", "metadata"}
            or entry["filename"] != wheel["file"] or entry["sha256Digest"] != wheel["sha256"]
            or entry["downloadUrl"] != expected_url or entry["metadata"].get("version") != wheel["version"]):
        raise ValueError("Prepared publication metadata does not match the qualified candidate.")
    return candidate, value


def publish(directory, receipt, prepared):
    publication_allowed()
    candidate, preparation = verify_publication_inputs(directory, prepared)
    version = candidate["wheel"]["version"]
    tag = f"v{version}"
    existing_tag = tag_commit(tag)
    if existing_tag is not None and existing_tag != candidate["sourceCommit"]:
        raise ValueError("Existing release tag points to another commit; it will not be moved.")
    release = find_release(tag)
    if release is None:
        release = github(f"repos/{REPOSITORY}/releases", method="POST", data={
            "tag_name": tag, "target_commitish": candidate["sourceCommit"],
            "name": f"azure-iot {version}", "draft": True,
            "prerelease": preparation["prerelease"], "generate_release_notes": True,
        })
    if (release["target_commitish"] != candidate["sourceCommit"] and existing_tag != candidate["sourceCommit"]
            or release["prerelease"] != preparation["prerelease"]):
        raise ValueError("Existing release has different source or prerelease metadata.")
    for asset in (candidate["wheel"], candidate["sbom"]):
        matches = [item for item in release["assets"] if item["name"] == asset["file"]]
        if len(matches) > 1:
            raise ValueError("Duplicate release assets.")
        if matches:
            if matches[0].get("digest") != "sha256:" + asset["sha256"]:
                raise ValueError("Existing asset differs or has no verifiable digest; refusing overwrite.")
        else:
            if not release["draft"]:
                raise ValueError("Published release is incomplete; refusing to mutate its assets.")
            uploaded = api(
                f"https://uploads.github.com/repos/{REPOSITORY}/releases/{release['id']}/assets?"
                + urlencode({"name": asset["file"]}), environment("RELEASE_GITHUB_TOKEN"),
                method="POST", data=(directory / asset["file"]).read_bytes(),
                content_type="application/octet-stream",
            )
            if uploaded.get("digest") != "sha256:" + asset["sha256"]:
                raise ValueError("Uploaded release asset digest mismatch; release remains a draft.")
    if release["draft"]:
        current_tag = tag_commit(tag)
        if current_tag is None:
            github(f"repos/{REPOSITORY}/git/refs", method="POST",
                   data={"ref": f"refs/tags/{tag}", "sha": candidate["sourceCommit"]})
        elif current_tag != candidate["sourceCommit"]:
            raise ValueError("Tag changed during staging; release remains a draft.")
        github(f"repos/{REPOSITORY}/releases/{release['id']}", method="PATCH", data={"draft": False})
    verify_public_assets(github(f"repos/{REPOSITORY}/releases/{release['id']}"), candidate)
    if tag_commit(tag) != candidate["sourceCommit"]:
        raise ValueError("Published tag no longer matches the qualified commit.")
    wheel_url = f"https://github.com/{REPOSITORY}/releases/download/{tag}/{candidate['wheel']['file']}"
    result = {"release": release["id"], "tag": tag, "wheelUrl": wheel_url, "candidate": candidate}
    write(receipt, result)
    print(f"Published https://github.com/{REPOSITORY}/releases/tag/{tag}", flush=True)
    return result


def index_pull_request(directory, receipt, work_dir, prepared):
    publication_allowed()
    if not release_options()[1]:
        raise ValueError("Index submission requires explicit createIndexPr opt-in.")
    candidate, preparation = verify_publication_inputs(directory, prepared)
    publication = read(receipt)
    if publication["candidate"] != candidate:
        raise ValueError("Publication receipt belongs to a different candidate.")
    expected_url = (f"https://github.com/{REPOSITORY}/releases/download/"
                    f"v{candidate['wheel']['version']}/{candidate['wheel']['file']}")
    if publication["wheelUrl"] != expected_url:
        raise ValueError("Index URL differs from the qualified release.")
    release = find_release(publication["tag"])
    if (release is None or release["draft"] or release["id"] != publication["release"]
            or tag_commit(publication["tag"]) != candidate["sourceCommit"]):
        raise ValueError("A public release of the qualified commit is required before index submission.")
    verify_public_assets(release, candidate)
    fork = environment("INDEX_FORK_REPOSITORY")
    if not re.fullmatch(r"[A-Za-z0-9-]+/azure-cli-extensions", fork) or fork == INDEX_REPOSITORY:
        raise ValueError("Configure an approved automation fork, not the upstream index repository.")
    fork_info = github(f"repos/{fork}")
    if not fork_info.get("fork") or fork_info.get("parent", {}).get("full_name") != INDEX_REPOSITORY:
        raise ValueError("The configured repository is not a fork of the official index.")
    work_dir.mkdir(parents=True, exist_ok=True)
    source_sha = commit(github(f"repos/{INDEX_REPOSITORY}/git/ref/heads/main")["object"]["sha"])
    before = json.loads(github_contents(INDEX_REPOSITORY, source_sha))
    prior = before["extensions"].get("azure-iot", [])
    same_version = [entry for entry in prior if entry["metadata"]["version"] == candidate["wheel"]["version"]]
    if same_version:
        if (len(same_version) != 1 or same_version[0]["sha256Digest"] != candidate["wheel"]["sha256"]
                or same_version[0]["downloadUrl"] != expected_url):
            raise ValueError("The index already contains conflicting metadata for this version.")
        print("The exact candidate is already indexed; no duplicate PR was created.")
        return {"status": "already-indexed"}
    after = json.loads(json.dumps(before))
    added = preparation["indexEntry"]
    after["extensions"].setdefault("azure-iot", []).append(added)
    verify_index_change(before, after, added)
    if (added["metadata"]["version"] != candidate["wheel"]["version"]
            or added["sha256Digest"] != candidate["wheel"]["sha256"]
            or added["filename"] != candidate["wheel"]["file"] or added["downloadUrl"] != expected_url):
        raise ValueError("Index update changed more than the verified candidate entry.")
    index_path = work_dir / "index.json"
    index_path.write_text(json.dumps(after, indent=4, sort_keys=True), encoding="utf-8")
    release_branch = f"release/azure-iot-{candidate['wheel']['version']}"
    ref = github(f"repos/{fork}/git/ref/heads/{quote(release_branch, safe='')}", missing=True)
    encoded = base64.b64encode(index_path.read_bytes()).decode()
    if ref:
        contents = github_contents(fork, release_branch)
        if ref["object"]["sha"] != source_sha:
            verify_existing_index_branch(fork, release_branch, contents, added)
        elif contents != index_path.read_bytes():
            old = github(f"repos/{fork}/contents/src/index.json?" + urlencode({"ref": release_branch}))
            github(f"repos/{fork}/contents/src/index.json", method="PUT", data={
                "message": f"Update azure-iot to {candidate['wheel']['version']}",
                "content": encoded, "sha": old["sha"], "branch": release_branch,
            })
    else:
        github(f"repos/{fork}/git/refs", method="POST",
               data={"ref": f"refs/heads/{release_branch}", "sha": source_sha})
        old = github(f"repos/{fork}/contents/src/index.json?" + urlencode({"ref": release_branch}))
        github(f"repos/{fork}/contents/src/index.json", method="PUT", data={
            "message": f"Update azure-iot to {candidate['wheel']['version']}",
            "content": encoded, "sha": old["sha"], "branch": release_branch,
        })
    head = f"{fork.split('/')[0]}:{release_branch}"
    existing = github(f"repos/{INDEX_REPOSITORY}/pulls?" + urlencode({"head": head, "base": "main", "state": "open"}))
    if len(existing) > 1:
        raise ValueError("Multiple open index PRs reference the release branch.")
    result = existing[0] if existing else github(f"repos/{INDEX_REPOSITORY}/pulls", method="POST", data={
        "title": f"[azure-iot] Update to {candidate['wheel']['version']}", "head": head, "base": "main",
        "body": (f"Release: https://github.com/{REPOSITORY}/releases/tag/{publication['tag']}\n\n"
                 f"Source: `{candidate['sourceCommit']}`\n\nWheel SHA-256: `{candidate['wheel']['sha256']}`\n\n"
                 "Qualified by the Azure IoT CLI ADO release pipeline. Index-team review is required; "
                 "this automation does not merge the PR."),
    })
    print(f"Index review required: {result['html_url']}", flush=True)
    return {"status": "review-required", "url": result["html_url"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=[
        "options", "plan", "resolve", "checkout", "build", "candidate", "verify", "integrate", "cancel",
        "verify-integration", "index-check", "feed-environment", "prepare-publication", "publish", "index",
        "unit-constraints", "unit-inventory",
        "runtime-receipt", "windows-runtime", "assemble-runtime",
    ])
    parser.add_argument("--source", type=Path)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--record", type=Path)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--prepared", type=Path)
    parser.add_argument("--inventory", type=Path)
    args = parser.parse_args()
    if args.operation == "options":
        mode, create_index_pr = release_options()
        print(json.dumps({"mode": mode, "createIndexPr": create_index_pr}))
    elif args.operation == "plan":
        print(json.dumps({
            "sourceBranch": branch(environment("RELEASE_SOURCE_BRANCH")),
            "mode": "Plan only; governed onboarding; no qualification, release, tag, or index PR.",
            "integrationPipeline": 147, "unitMatrix": "Python 3.10-3.13 on Ubuntu, Windows and macOS",
            "cohorts": integration_cohorts(),
        }, indent=2))
    elif args.operation in ("resolve", "checkout"):
        checkout(args.source, resolving=args.operation == "resolve")
    elif args.operation == "candidate":
        create_candidate(args.source, args.directory)
    elif args.operation == "build":
        build_candidate(args.source, args.work_dir, args.inventory)
    elif args.operation in ("unit-constraints", "unit-inventory"):
        unit_dependencies(args.source, args.directory, check=args.operation == "unit-inventory")
    elif args.operation == "runtime-receipt":
        runtime_receipt(args.source, args.directory, args.inventory)
    elif args.operation == "windows-runtime":
        windows_runtime(args.source, args.directory, args.work_dir, args.inventory)
    elif args.operation == "assemble-runtime":
        assemble_runtime(args.source, args.directory)
    elif args.operation == "feed-environment":
        configure_feed()
    elif args.operation == "prepare-publication":
        prepare_publication(args.directory, args.prepared, args.work_dir)
    elif args.operation == "verify":
        verify_candidate(args.directory)
    elif args.operation == "integrate":
        integrate(args.directory, args.record)
    elif args.operation == "cancel":
        cancel_integration(args.record, args.directory)
    elif args.operation == "verify-integration":
        verify_integration_artifacts(args.directory, args.work_dir)
    elif args.operation == "publish":
        publish(args.directory, args.record, args.prepared)
    elif args.operation == "index-check":
        index_check(args.source, args.directory, args.work_dir)
    elif args.operation == "index":
        result = index_pull_request(args.directory, args.record, args.work_dir, args.prepared)
        write(args.work_dir / "index-pr.json", result)


if __name__ == "__main__":
    main()
