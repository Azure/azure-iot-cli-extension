# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Resource-specific Hub request projections, independent of generated models.

None at a modeled property means omission; None inside user dictionaries is a
JSON deletion marker. Never recursively scrub user tags, content or payloads.
"""

from copy import deepcopy

from azure.cli.core.azclierror import InvalidArgumentValueError
from knack.util import to_snake_case
from msrest.exceptions import SerializationError
from msrest.serialization import Deserializer, Serializer


def _fields(names, **children):
    return dict.fromkeys(names.split(), None) | children


_THUMBPRINT = _fields("primaryThumbprint secondaryThumbprint")
_AUTH = _fields(
    "type policyResourceId x509CaValidation",
    symmetricKey=_fields("primaryKey secondaryKey"),
    x509Thumbprint=_THUMBPRINT,
)
_CAPABILITIES = _fields("iotEdge")
_TWIN_PROPERTIES = _fields("desired reported")
_METRICS = _fields("results queries")
_CONTENT = _fields("deviceContent moduleContent modulesContent")
_METHOD = _fields("methodName payload connectTimeoutInSeconds responseTimeoutInSeconds")
OWNED_IDENTITY_FIELDS = ("adrDeviceProperties", "deviceResourceId", "armSyncStatus")

SCHEMAS = {
    "Device": _fields(
        "deviceId generationId etag connectionState status statusReason cloudToDeviceMessageCount "
        "deviceScope parentScopes attributes",
        authentication=_AUTH, capabilities=_CAPABILITIES,
        connectionStateUpdatedTime="date", statusUpdatedTime="date", lastActivityTime="date",
    ),
    "Module": _fields(
        "deviceId moduleId managedBy generationId etag connectionState cloudToDeviceMessageCount attributes",
        authentication=_AUTH, connectionStateUpdatedTime="date", lastActivityTime="date",
    ),
    "Twin": _fields(
        "deviceId moduleId tags etag version deviceEtag status statusReason connectionState "
        "cloudToDeviceMessageCount authenticationType deviceScope parentScopes attributes",
        properties=_TWIN_PROPERTIES, capabilities=_CAPABILITIES, x509Thumbprint=_THUMBPRINT,
        statusUpdateTime="date", lastActivityTime="date",
    ),
    "Configuration": _fields(
        "id schemaVersion labels targetCondition priority etag",
        content=_CONTENT, metrics=_METRICS, systemMetrics=_METRICS,
        createdTimeUtc="date", lastUpdatedTimeUtc="date",
    ),
    "ConfigurationContent": _CONTENT,
    "ConfigurationMetrics": _METRICS,
    "AuthenticationMechanism": _AUTH,
    "SymmetricKey": _fields("primaryKey secondaryKey"),
    "X509Thumbprint": _THUMBPRINT,
    "DeviceCapabilities": _CAPABILITIES,
    "CloudToDeviceMethod": _METHOD,
    "ManagedIdentity": _fields("userAssignedIdentity"),
    "FileUploadRequest": _fields("blobName"),
    "FileUploadCompletionStatus": _fields("correlationId isSuccess statusCode statusDescription"),
    "JobProperties": _fields(
        "jobId type status progress inputBlobContainerUri inputBlobName outputBlobContainerUri "
        "outputBlobName excludeKeysInExport storageAuthenticationType failureReason "
        "includeConfigurations configurationsBlobName",
        identity=_fields("userAssignedIdentity"), startTimeUtc="date", endTimeUtc="date",
    ),
}
SCHEMAS["JobRequest"] = _fields(
    "jobId type queryCondition maxExecutionTimeInSeconds",
    updateTwin=SCHEMAS["Twin"], cloudToDeviceMethod=_METHOD, startTime="date",
)
SCHEMAS["ExportImportDevice"] = _fields(
    "id moduleId eTag importMode status statusReason twinETag tags deviceScope parentScopes",
    authentication=_AUTH, capabilities=_CAPABILITIES, properties=_TWIN_PROPERTIES,
)


def _project(value, schema):
    if schema == "date":
        return Serializer().serialize_data(Deserializer.deserialize_iso(value), "iso-8601")
    if schema is None:
        return deepcopy(value)
    if not isinstance(value, dict):
        raise SerializationError("Hub request properties must be JSON objects.")
    result = {}
    for name, child in schema.items():
        item = value.get(name, value.get(to_snake_case(name)))
        if item is not None:
            result[name] = _project(item, child)
    return result


def project(model, value):
    """Project only modeled resource fields; ADR-owned properties are not writable."""
    return _project(value, SCHEMAS[model])


def make_payload(model, **properties):
    """Build a wire dictionary from the CLI's keyword-style property names."""
    return project(model, properties)


def restore_identity_properties(created, snapshot):
    """Retain writable snapshot extensions, never source-owned identity metadata."""
    if snapshot:
        for name, schema in (("authentication", _AUTH), ("attributes", None)):
            if snapshot.get(name) is not None:
                created[name] = _project(snapshot[name], schema)
    return created


def validate_identity_update(namespace):
    """Reject explicit generic mutation of ADR-owned top-level identity metadata."""
    for operation, values in getattr(namespace, "ordered_arguments", None) or []:
        paths = values if operation == "--set" else values[:1]
        for value in paths:
            path = value.split("=", 1)[0].split(".", 1)[0].split("[", 1)[0]
            if path.replace("_", "").lower() in {name.lower() for name in OWNED_IDENTITY_FIELDS}:
                raise InvalidArgumentValueError(f"{path} is owned by ADR/ARM and cannot be modified.")
