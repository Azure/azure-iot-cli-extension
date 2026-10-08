# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline provenance verification and narrowly scoped ADO build metadata lookup (stdlib only)."""

import argparse
from email.parser import BytesParser
import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import stat
import sys
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request
import zipfile

REPOSITORY = "Azure/azure-iot-cli-extension"
COMMIT = r"[0-9a-fA-F]{40}"
GUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"


class ProvenanceError(ValueError):
    """A static, safe-to-log provenance failure."""


def require(condition, message):
    if not condition:
        raise ProvenanceError(message)


def matches(pattern, value):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def object_value(value):
    require(isinstance(value, dict), "Provenance must contain JSON objects.")
    return value


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON provenance field.")
        result[key] = value
    return result


def read_json(path):
    try:
        return object_value(json.loads(Path(path).read_bytes(), object_pairs_hook=unique_object))
    except (OSError, ValueError) as error:
        raise ProvenanceError("Missing or invalid provenance JSON.") from error


def configuration(env):
    build = env.get("RELEASE_BUILD_ID", "")
    definition = env.get("RELEASE_PIPELINE_ID", "")
    require(matches(r"[1-9][0-9]*", build), "releaseBuildId must be a positive integer in external mode.")
    require(matches(r"[1-9][0-9]*", definition),
            "ReleasePipelineId must be configured as a positive integer; unresolved values are not trusted.")
    project = env.get("SYSTEM_TEAMPROJECTID", "")
    require(matches(GUID, project), "System.TeamProjectId must identify the current project.")
    return build, definition, project


def validate_parent(value, env):
    build, definition, project = configuration(env)
    value = object_value(value)
    actual_definition = object_value(value.get("definition"))
    actual_project = object_value(value.get("project"))
    repository = object_value(value.get("repository"))
    require(type(value.get("id")) is int and str(value["id"]) == build, "Producer build ID mismatch.")
    require(type(actual_definition.get("id")) is int and str(actual_definition["id"]) == definition,
            "Producer definition does not match ReleasePipelineId.")
    require(isinstance(actual_project.get("id"), str) and actual_project["id"].lower() == project.lower(),
            "Producer project mismatch.")
    if "project" in actual_definition:
        definition_project = object_value(actual_definition["project"]).get("id")
        require(matches(GUID, definition_project) and definition_project.lower() == project.lower(),
                "Producer definition project mismatch.")
    repository_name = repository.get("name")
    require(repository.get("type") == "GitHub"
            and isinstance(repository.get("id"), str) and repository["id"].lower() == REPOSITORY.lower()
            and (repository_name is None
                 or (isinstance(repository_name, str) and repository_name.lower() == REPOSITORY.lower())),
            "Producer repository mismatch.")
    require(matches(COMMIT, value.get("sourceVersion")), "Producer automation commit is invalid.")
    require((value.get("status") == "inProgress" and value.get("result") in (None, "none"))
            or (value.get("status") == "completed" and value.get("result") == "succeeded"),
            "Producer must be in progress or successfully completed; failed/canceled builds are not trusted.")
    # Keep only verification fields, never REST links or artifact download URLs.
    return {
        "id": value["id"], "definition": {"id": actual_definition["id"]},
        "project": {"id": actual_project["id"]},
        "repository": {"id": repository["id"], "name": repository_name, "type": repository["type"]},
        "sourceVersion": value["sourceVersion"], "status": value["status"], "result": value.get("result"),
    }


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProvenanceError("ADO metadata redirects are not permitted.")


def fetch_parent(env):
    build, _, project = configuration(env)
    collection = env.get("SYSTEM_COLLECTIONURI", "")
    uri = urlsplit(collection)
    require(uri.scheme == "https" and (uri.hostname == "dev.azure.com"
                                       or (uri.hostname or "").endswith(".visualstudio.com"))
            and not uri.username and not uri.password and uri.port in (None, 443)
            and not uri.query and not uri.fragment,
            "System.CollectionUri must be an HTTPS Azure DevOps collection URL.")
    token = env.get("SYSTEM_ACCESSTOKEN", "")
    require(bool(token) and not token.startswith("$("), "System.AccessToken is required for metadata lookup.")
    url = f"{collection.rstrip('/')}/{project}/_apis/build/builds/{build}?api-version=7.1"
    request = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            require(response.status == 200, "ADO metadata lookup did not return HTTP 200.")
            value = json.load(response, object_pairs_hook=unique_object)
    except (URLError, OSError, ValueError, HTTPException) as error:
        # Exceptions can contain authenticated URLs or response bodies. Never echo them.
        raise ProvenanceError("ADO build metadata lookup failed; check scoped build-read access.") from error
    return validate_parent(value, env)


def safe_archive_path(name):
    return (isinstance(name, str) and bool(name) and "\\" not in name and ":" not in name
            and not any(ord(char) < 32 for char in name)
            and all(part not in ("", ".", "..") for part in name.rstrip("/").split("/")))


def verify_wheel(path, wheel):
    filename, version = wheel.get("file"), wheel.get("version")
    require(matches(r"[0-9][A-Za-z0-9_.+!]*", version), "Candidate wheel version is invalid.")
    parts = filename[:-4].split("-")
    require(len(parts) in (5, 6) and parts[:2] == ["azure_iot", version]
            and all(matches(r"[A-Za-z0-9_.]+", tag) for tag in parts[-3:])
            and (len(parts) == 5 or matches(r"[0-9][A-Za-z0-9_]*", parts[2])),
            "Wheel filename distribution/version mismatch.")
    require(matches(r"[0-9a-fA-F]{64}", wheel.get("sha256"))
            and hashlib.sha256(path.read_bytes()).hexdigest() == wheel["sha256"].lower(),
            "Candidate wheel SHA256 mismatch.")
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            require(len(names) == len(set(names)) and all(
                safe_archive_path(entry.filename) and not stat.S_ISLNK(entry.external_attr >> 16)
                for entry in entries), "Wheel contains unsafe or duplicate archive paths.")
            metadata = [name for name in names if name.endswith(".dist-info/METADATA")]
            require(metadata == [f"azure_iot-{version}.dist-info/METADATA"],
                    "Wheel must contain exactly one matching distribution METADATA.")
            require(archive.getinfo(metadata[0]).file_size <= 1024 * 1024, "Wheel METADATA is too large.")
            headers = BytesParser().parsebytes(archive.read(metadata[0]), headersonly=True)
            names = headers.get_all("Name", [])
            require(len(names) == 1 and re.sub(r"[-_.]+", "-", names[0]).lower() == "azure-iot",
                    "Wheel METADATA distribution must be azure-iot.")
            require(headers.get_all("Version", []) == [version], "Wheel METADATA version mismatch.")
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
        raise ProvenanceError("Candidate wheel archive is invalid.") from error


def verify_candidate(directory, parent, env):
    parent = validate_parent(parent, env)
    require(env.get("BUILD_REPOSITORY_NAME", "").lower() == REPOSITORY.lower(), "Child repository mismatch.")
    commit, branch = env.get("BUILD_SOURCEVERSION", ""), env.get("BUILD_SOURCEBRANCH", "")
    require(matches(COMMIT, commit) and branch.startswith("refs/heads/") and len(branch) > len("refs/heads/"),
            "Child source commit/branch is invalid.")
    directory = Path(directory)
    require(directory.is_dir() and not directory.is_symlink(), "Candidate artifact directory is missing or unsafe.")
    manifest_path = directory / "candidate.json"
    require(manifest_path.is_file() and not manifest_path.is_symlink(), "Candidate manifest is missing or unsafe.")
    manifest = read_json(manifest_path)
    require(type(manifest.get("schema")) is int and manifest["schema"] == 1, "Unsupported candidate manifest schema.")
    require(manifest.get("repository") == REPOSITORY, "Candidate repository mismatch.")
    require(manifest.get("sourceCommit") == commit and manifest.get("sourceBranch") == branch,
            "Candidate source commit/branch must exactly match this integration build.")
    producer = object_value(manifest.get("producer"))
    require(producer == {"definition": str(parent["definition"]["id"]), "build": str(parent["id"]),
                         "commit": parent["sourceVersion"]}, "Candidate producer does not match retrieved build metadata.")
    wheel = object_value(manifest.get("wheel"))
    filename = wheel.get("file")
    require(matches(r"azure_iot-[A-Za-z0-9_.+!-]+\.whl", filename), "Candidate wheel filename must be a safe basename.")
    files = list(directory.iterdir())
    require({path.name for path in files} == {filename, "candidate.json", "SBOM.zip"}
            and all(path.is_file() and not path.is_symlink() for path in files),
            "Candidate artifact must contain only one wheel, candidate.json and SBOM.zip as regular files.")
    verify_wheel(directory / filename, wheel)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("parent", "verify"))
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--candidate")
    args = parser.parse_args(argv)
    try:
        if args.action == "parent":
            parent = fetch_parent(os.environ)
            Path(args.metadata).write_text(json.dumps(parent), encoding="utf-8")
        else:
            require(bool(args.candidate), "Candidate directory is required.")
            verify_candidate(args.candidate, read_json(args.metadata), os.environ)
    except ProvenanceError as error:
        print(f"Release candidate rejected: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, KeyError):
        # Malformed files/environment must fail closed without exposing their contents.
        print("Release candidate rejected: invalid or unreadable provenance.", file=sys.stderr)
        return 1
    print("Release producer validated." if args.action == "parent" else "Release candidate verified without rebuilding.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
