# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Resolve and acquire published CLI releases without Azure credentials or live tests."""

import argparse
import ast
from email.parser import Parser
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zipfile import ZipFile

from packaging.version import InvalidVersion, Version


REPOSITORIES = {
    "azure-iot": "Azure/azure-iot-cli-extension",
    "azure-iot-ops": "Azure/azure-iot-ops-cli-extension",
}
CLOUDS = {"public": "AzureCloud", "fairfax": "AzureUSGovernment", "mooncake": "AzureChinaCloud"}
HOSTS = {
    "api.github.com", "raw.githubusercontent.com", "github.com",
    "release-assets.githubusercontent.com", "objects.githubusercontent.com",
}
TEMPLATE = "azext_edge/edge/providers/orchestration/template{}.py"
MAX_BYTES = 64 * 1024 * 1024


class NonStableRuntime(ValueError):
    """A published CLI's bundled runtime is not a stable monitor target."""


def validate_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.hostname not in HOSTS or parsed.port not in (None, 443)
            or parsed.username is not None or parsed.password is not None or parsed.fragment):
        raise ValueError("Release downloads require an approved, credential-free GitHub HTTPS URL.")


class ReleaseRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url):
    validate_url(url)
    request = Request(url, headers={"User-Agent": "azure-iot-release-monitor"})
    with build_opener(ReleaseRedirectHandler()).open(request, timeout=60) as response:
        validate_url(response.url)
        value = response.read(MAX_BYTES + 1)
    if len(value) > MAX_BYTES:
        raise ValueError("Release download exceeds the size limit.")
    return value


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def commit(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("An immutable 40-character source commit is required.")
    return value


def settings(extension):
    if extension not in REPOSITORIES:
        raise ValueError("Unknown monitored extension.")
    return {
        "extension": extension, "repository": REPOSITORIES[extension],
        "package": "azext_iot" if extension == "azure-iot" else "azext_edge",
    }


def tag_commit(repository, tag):
    ref = f"refs/tags/{tag}"
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", f"https://github.com/{repository}.git", ref, ref + "^{}"],
        check=True, capture_output=True, text=True, timeout=60,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    refs = dict(line.split()[::-1] for line in result.stdout.splitlines())
    return commit(refs.get(ref + "^{}", refs.get(ref)))


def published_releases(repository):
    releases = []
    for page in range(1, 11):
        values = json.loads(download(f"https://api.github.com/repos/{repository}/releases?per_page=100&page={page}"))
        if not isinstance(values, list):
            raise ValueError("GitHub did not return a release list.")
        releases.extend(values)
        if len(values) < 100:
            return releases
    raise ValueError("Release discovery exceeded its pagination limit.")


def release_version(release):
    tag = release.get("tag_name", "")
    if not isinstance(tag, str) or not re.fullmatch(r"v[0-9][0-9A-Za-z.+-]*", tag):
        raise ValueError("Published release has an invalid version tag.")
    try:
        version = Version(tag[1:])
    except InvalidVersion as error:
        raise ValueError("Published release has an invalid version tag.") from error
    if version.is_devrelease or version.local:
        raise ValueError("Development and local builds are not published monitor targets.")
    return version


def parse_runtime_profile(source, cloud):
    profiles = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Dict):
            continue
        values = {key.value: value for key, value in zip(node.keys, node.values)
                  if isinstance(key, ast.Constant) and isinstance(key.value, str)}
        if "VERSIONS" not in values or "TRAINS" not in values:
            continue
        versions, trains = ast.literal_eval(values["VERSIONS"]), ast.literal_eval(values["TRAINS"])
        if "iotOperations" not in versions:
            continue
        version = Version(versions["iotOperations"])
        train = trains.get("iotOperations")
        if not isinstance(train, str) or not train:
            raise ValueError("The bundled runtime is missing its release train.")
        profiles.append({
            "milestone": f"{version.major}.{version.minor}", "version": str(version),
            "train": train, "template": TEMPLATE.format("_fairfax" if cloud == "fairfax" else ""),
        })
    if len(profiles) != 1:
        raise ValueError("The release does not contain one unambiguous stable runtime profile.")
    version = Version(profiles[0]["version"])
    if version.is_prerelease or version.is_devrelease or profiles[0]["train"] != "stable":
        raise NonStableRuntime("A monitored milestone must have a stable bundled runtime.")
    return profiles[0]


def runtime_profile(repository, source_commit, cloud):
    suffix = "_fairfax" if cloud == "fairfax" else ""
    url = f"https://raw.githubusercontent.com/{repository}/{commit(source_commit)}/{TEMPLATE.format(suffix)}"
    try:
        source = download(url).decode("utf-8")
    except HTTPError as error:
        if error.code == 404:
            return None
        raise
    return parse_runtime_profile(source, cloud)


def wheel_asset(release, extension, version):
    name = f"{extension.replace('-', '_')}-{version}-py3-none-any.whl"
    assets = [asset for asset in release.get("assets", []) if asset.get("name") == name]
    if len(assets) != 1:
        raise ValueError(f"Published release must contain exactly one {name}.")
    asset = assets[0]
    digest = asset.get("digest", "")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("The published wheel is missing its GitHub SHA256 digest.")
    expected = f"https://github.com/{REPOSITORIES[extension]}/releases/download/{release['tag_name']}/{name}"
    if asset.get("browser_download_url") != expected:
        raise ValueError("Wheel asset URL does not belong to the selected release.")
    return {"name": name, "url": expected, "sha256": digest.removeprefix("sha256:")}


def resolve(extension, cloud, track, automation_commit, releases=None):
    config = settings(extension)
    if cloud not in CLOUDS or extension == "azure-iot-ops" and cloud == "mooncake":
        raise ValueError("This product/cloud combination is not supported.")
    if (extension == "azure-iot" and track not in {"ga", "preview"}
            or extension == "azure-iot-ops" and not re.fullmatch(r"[1-9][0-9]*\.[0-9]+", track)):
        raise ValueError("Select GA/Preview for IoT or an explicit runtime milestone for AIO.")
    automation_commit = commit(automation_commit)
    releases = published_releases(config["repository"]) if releases is None else releases
    candidates = []
    for item in releases:
        if item.get("draft"):
            continue
        version = release_version(item)
        preview = bool(item.get("prerelease")) or version.is_prerelease
        if preview != (extension == "azure-iot" and track == "preview"):
            continue
        candidates.append((version, item))
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    selected, runtime = None, None
    milestones = {}
    for version, release in candidates:
        source_commit = tag_commit(config["repository"], release["tag_name"])
        if extension == "azure-iot":
            selected = (version, release, source_commit)
            break
        try:
            profile = runtime_profile(config["repository"], source_commit, "public")
        except NonStableRuntime:
            print(f"Skipping published CLI {release['tag_name']}: no stable bundled Public runtime.", file=sys.stderr)
            continue
        if profile is None:
            raise ValueError("A published AIO release is missing its Public runtime profile.")
        family = profile["milestone"]
        if family not in milestones:
            milestones[family] = (version, release, source_commit)
        if len(milestones) == 3:
            break
    if extension == "azure-iot-ops":
        if len(milestones) != 3 or track not in milestones:
            raise ValueError("The requested milestone is not in the latest three published runtime families.")
        selected = milestones[track]
        runtime = runtime_profile(config["repository"], selected[2], cloud)
        if runtime is not None and runtime["milestone"] != track:
            raise ValueError("The cloud-specific runtime does not belong to the selected milestone.")
    if selected is None:
        raise ValueError("No matching published release was found.")
    version, release, source_commit = selected
    blockers = []
    if extension == "azure-iot-ops" and runtime is None:
        blockers.append("This release has no reviewed bundled runtime profile for the selected cloud.")
    return {
        "schema": 1, **config, "cloud": CLOUDS[cloud], "cloudKey": cloud, "track": track,
        "automationCommit": automation_commit,
        "release": {
            "id": release["id"], "tag": release["tag_name"], "version": str(version), "commit": source_commit,
        },
        "wheel": wheel_asset(release, extension, version), "runtime": runtime,
        "testSourceCommit": source_commit, "blockers": blockers,
        "releaseQualified": False,
    }


def validate_manifest(manifest, *, extension=None, cloud=None, track=None, automation_commit=None):
    config = settings(manifest["extension"])
    if any(manifest.get(key) != value for key, value in config.items()) or manifest.get("schema") != 1:
        raise ValueError("Invalid release manifest repository or schema.")
    cloud_key = manifest["cloudKey"]
    if (cloud_key not in CLOUDS or manifest["cloud"] != CLOUDS[cloud_key]
            or manifest["extension"] == "azure-iot-ops" and cloud_key == "mooncake"):
        raise ValueError("Invalid release manifest cloud.")
    for key, expected in (
        ("extension", extension), ("cloudKey", cloud), ("track", track), ("automationCommit", automation_commit),
    ):
        if expected is not None and manifest.get(key) != expected:
            raise ValueError(f"Release manifest differs from the requested {key}.")
    commit(manifest["automationCommit"])
    if commit(manifest["testSourceCommit"]) != commit(manifest["release"]["commit"]):
        raise ValueError("Test source must match the released source commit.")
    version = release_version({"tag_name": manifest["release"]["tag"]})
    if str(version) != manifest["release"]["version"] or manifest.get("releaseQualified") is not False:
        raise ValueError("Invalid published version or release-qualification boundary.")
    expected_name = f"{config['extension'].replace('-', '_')}-{version}-py3-none-any.whl"
    expected_url = (
        f"https://github.com/{config['repository']}/releases/download/{manifest['release']['tag']}/{expected_name}"
    )
    if (manifest["wheel"].get("name") != expected_name or manifest["wheel"].get("url") != expected_url
            or not re.fullmatch(r"[0-9a-f]{64}", manifest["wheel"].get("sha256", ""))):
        raise ValueError("Invalid published wheel identity.")
    if config["extension"] == "azure-iot":
        if (manifest["track"] not in {"ga", "preview"} or manifest["runtime"] is not None
                or version.is_prerelease != (manifest["track"] == "preview")):
            raise ValueError("Invalid IoT release track.")
    else:
        runtime = manifest["runtime"]
        if (version.is_prerelease or not re.fullmatch(r"[1-9][0-9]*\.[0-9]+", manifest["track"])
                or runtime is not None and (
                    runtime["milestone"] != manifest["track"] or runtime["train"] != "stable"
                    or runtime["template"] != TEMPLATE.format("_fairfax" if cloud_key == "fairfax" else ""))):
            raise ValueError("Invalid AIO milestone profile.")
    expected_blockers = (
        ["This release has no reviewed bundled runtime profile for the selected cloud."]
        if config["extension"] == "azure-iot-ops" and manifest["runtime"] is None else []
    )
    if manifest["blockers"] != expected_blockers:
        raise ValueError("Release capability blockers do not match its runtime profile.")
    return manifest


def verify_wheel(path, manifest):
    validate_manifest(manifest)
    path = Path(path)
    if (path.name != manifest["wheel"]["name"]
            or hashlib.sha256(path.read_bytes()).hexdigest() != manifest["wheel"]["sha256"]):
        raise ValueError("Released wheel filename or SHA256 does not match the frozen manifest.")
    with ZipFile(path) as archive:
        metadata = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata) != 1 or f"{manifest['package']}/__init__.py" not in archive.namelist():
            raise ValueError("Released artifact is not the selected CLI extension wheel.")
        headers = Parser().parsestr(archive.read(metadata[0]).decode("utf-8"))
        if (not headers["Name"] or not headers["Version"]
                or headers["Name"].replace("_", "-") != manifest["extension"]
                or Version(headers["Version"]) != Version(manifest["release"]["version"])):
            raise ValueError("Wheel metadata does not match the selected release.")
        if manifest["runtime"]:
            profile = parse_runtime_profile(
                archive.read(manifest["runtime"]["template"]).decode("utf-8"), manifest["cloudKey"],
            )
            if profile != manifest["runtime"]:
                raise ValueError("Wheel runtime differs from the resolved release source.")


def verify_bundle(directory, **expected):
    directory = Path(directory)
    manifest = validate_manifest(read_json(directory / "manifest.json"), **expected)
    wheel = directory / manifest["wheel"]["name"]
    verify_wheel(wheel, manifest)
    source = directory / "source"
    snapshot = directory / "source.json"
    if hashlib.sha256(snapshot.read_bytes()).hexdigest() != manifest.get("sourceSha256"):
        raise ValueError("Released source inventory does not match the acquired bundle.")
    inventory = read_json(snapshot)
    if inventory["commit"] != manifest["testSourceCommit"] or inventory["files"] != source_files(source):
        raise ValueError("Released test source is missing, modified, or belongs to a different commit.")
    with ZipFile(wheel) as archive:
        prefix = manifest["package"] + "/"
        entries = {name for name in archive.namelist() if name.startswith(prefix) and not name.endswith("/")}
        for name in entries:
            path = source / name
            if not path.is_file() or path.is_symlink() or path.read_bytes() != archive.read(name):
                raise ValueError(f"Release source differs from the published wheel: {name}")
        for path in (source / manifest["package"]).rglob("*.py"):
            relative = path.relative_to(source).as_posix()
            if not relative.startswith(prefix + "tests/") and relative not in entries:
                raise ValueError(f"Release source contains product code absent from the wheel: {relative}")
    return manifest


def source_files(source):
    files = {}
    for path in sorted(Path(source).rglob("*")):
        relative = path.relative_to(source)
        if relative.parts[0] == ".git":
            continue
        if path.is_symlink():
            raise ValueError("Released test source must not contain symbolic links.")
        if path.is_file():
            files[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not files:
        raise ValueError("Released test source is empty.")
    return files


def acquire(manifest, output):
    validate_manifest(manifest)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    wheel = output / manifest["wheel"]["name"]
    wheel.write_bytes(download(manifest["wheel"]["url"]))
    verify_wheel(wheel, manifest)
    source = output / "source"
    if source.exists():
        raise ValueError("Release-source destination already exists; use a fresh attempt directory.")
    source.mkdir()
    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    for arguments in (
        ["init", "--quiet"],
        ["fetch", "--quiet", "--depth=1", f"https://github.com/{manifest['repository']}.git",
         commit(manifest["testSourceCommit"])],
        ["checkout", "--quiet", "--detach", "FETCH_HEAD"],
    ):
        subprocess.run(["git", "-C", str(source), *arguments], check=True, env=environment, timeout=180)
    actual = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
    ).stdout.strip()
    if actual != manifest["testSourceCommit"]:
        raise ValueError("Downloaded test source does not match its frozen commit.")
    write_json(output / "source.json", {"commit": actual, "files": source_files(source)})
    source_digest = hashlib.sha256((output / "source.json").read_bytes()).hexdigest()
    if manifest.get("sourceSha256", source_digest) != source_digest:
        raise ValueError("The fixed release commit produced different test-source bytes.")
    manifest = {**manifest, "sourceSha256": source_digest}
    write_json(output / "manifest.json", manifest)
    verify_bundle(output)


def frozen_manifest(history, extension, cloud, track, automation_commit, attempt):
    paths = sorted(Path(history).glob("release-selection-*/manifest.json")) if history else []
    if not paths:
        if attempt != 1:
            raise ValueError("A retry cannot rediscover releases without its original frozen manifest.")
        return resolve(extension, cloud, track, automation_commit)
    values = [
        validate_manifest(read_json(path), extension=extension, cloud=cloud, track=track,
                          automation_commit=automation_commit)
        for path in paths
    ]
    if any(value != values[0] for value in values):
        raise ValueError("Release identity changed between attempts; start a new run.")
    return values[0]


def configurations(config):
    extension = config["extension"]
    settings(extension)
    tracks = config["tracks"]
    if len(set(tracks)) != len(tracks) or not tracks:
        raise ValueError("Monitor tracks must be nonempty and distinct.")
    if extension == "azure-iot" and set(tracks) != {"ga", "preview"}:
        raise ValueError("IoT monitoring requires GA and Preview.")
    if extension == "azure-iot-ops" and (
            len(tracks) != 3 or any(not re.fullmatch(r"[1-9][0-9]*\.[0-9]+", track) for track in tracks)):
        raise ValueError("AIO monitoring requires three explicit, distinct runtime milestones.")
    expected_clouds = {"public", "fairfax", "mooncake"} if extension == "azure-iot" else {"public", "fairfax"}
    if set(config["clouds"]) != expected_clouds:
        raise ValueError("Monitor clouds do not match the product's supported cloud matrix.")
    result = []
    for cloud, profile in config["clouds"].items():
        for track in tracks:
            label = {"ga": "GA", "preview": "Preview"}.get(track, track)
            result.append({
                "name": f"{config['namePrefix']} - {profile['displayName']} - {label}",
                "variables": {
                    "MonitorCloud": cloud, "MonitorTrack": track, "MonitorAzureCloud": CLOUDS[cloud],
                    **{name: value.format(track=track, cloud=cloud) for name, value in profile["variables"].items()},
                },
            })
    return result


def check_definition(config, extension, cloud, track):
    if config["extension"] != extension:
        raise ValueError("Monitor configuration belongs to a different extension.")
    matches = [
        item for item in configurations(config)
        if item["variables"]["MonitorCloud"] == cloud and item["variables"]["MonitorTrack"] == track
    ]
    if len(matches) != 1 or os.environ.get("BUILD_DEFINITIONNAME") != matches[0]["name"]:
        raise ValueError("This pipeline definition is not the selected version/cloud monitor.")
    if os.environ.get("BUILD_REPOSITORY_NAME", "").lower() != REPOSITORIES[extension].lower():
        raise ValueError("Monitor automation belongs to a different repository.")
    for name, expected in matches[0]["variables"].items():
        if os.environ.get(name.upper(), "") != expected:
            raise ValueError(f"{name} differs from the reviewed monitor configuration.")


def definitions(config, baseline, branch):
    repository = baseline["repository"]
    if (repository["name"].lower() != REPOSITORIES[config["extension"]].lower()
            or repository["type"].lower() != "github"
            or not re.fullmatch(r"refs/heads/[A-Za-z0-9._/-]+", branch) or ".." in branch):
        raise ValueError("Select the product's GitHub definition and an explicit automation branch.")
    source = {
        key: repository[key] for key in ("id", "name", "type", "url")
    }
    source["defaultBranch"] = branch
    source["properties"] = {"connectedServiceId": repository["properties"]["connectedServiceId"]}
    return [{
        "name": item["name"], "path": "\\official\\monitors", "type": "build",
        "queueStatus": "disabled", "triggers": [], "repository": source,
        "queue": {"id": baseline["queue"]["id"]},
        "process": {"type": 2, "yamlFilename": ".azure-devops/release-monitor.yml"},
        "variables": {
            name: {"value": value, "isSecret": False, "allowOverride": False}
            for name, value in item["variables"].items()
        },
    } for item in configurations(config)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("resolve")
    plan.add_argument("--extension", choices=REPOSITORIES, required=True)
    plan.add_argument("--cloud", choices=CLOUDS, required=True)
    plan.add_argument("--track", required=True)
    plan.add_argument("--automation-commit", required=True)
    plan.add_argument("--output", required=True)
    plan.add_argument("--history")
    plan.add_argument("--attempt", type=int, default=1)
    plan.add_argument("--configuration")
    fetch = commands.add_parser("acquire")
    fetch.add_argument("--manifest", required=True)
    fetch.add_argument("--output", required=True)
    setup = commands.add_parser("definitions")
    setup.add_argument("--configuration", required=True)
    setup.add_argument("--baseline", required=True)
    setup.add_argument("--branch", required=True)
    setup.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if args.command == "resolve":
        if args.configuration:
            check_definition(read_json(args.configuration), args.extension, args.cloud, args.track)
        value = frozen_manifest(
            args.history, args.extension, args.cloud, args.track, args.automation_commit, args.attempt,
        )
        write_json(args.output, value)
        print(json.dumps(value, indent=2))
    elif args.command == "acquire":
        acquire(read_json(args.manifest), args.output)
    else:
        write_json(args.output, definitions(read_json(args.configuration), read_json(args.baseline), args.branch))


if __name__ == "__main__":
    main()
