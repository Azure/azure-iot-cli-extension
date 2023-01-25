# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


DEVICE_UPDATE_MANIFEST_V5 = {
    "$id": "https://json.schemastore.org/azure-deviceupdate-import-manifest-5.0.json",
    "$schema": "http://json-schema.org/draft-07/schema",
    "definitions": {
        "instructions": {
            "type": "object",
            "title": "Installation instructions",
            "description": "Update installation instructions.",
            "properties": {
                "steps": {
                    "type": "array",
                    "title": "Installation steps",
                    "items": {"anyOf": [{"$ref": "#/definitions/inlineStep"}, {"$ref": "#/definitions/referenceStep"}]},
                    "minItems": 1,
                    "maxItems": 10,
                }
            },
            "additionalProperties": False,
            "required": ["steps"],
        },
        "stepDescription": {
            "type": "string",
            "title": "Step description",
            "description": "Optional instruction step description.",
            "minLength": 1,
            "maxLength": 64,
        },
        "inlineStep": {
            "type": "object",
            "title": "Inline installation step",
            "description": "Installation instruction step that performs code execution.",
            "properties": {
                "type": {"$ref": "azure-deviceupdate-manifest-definitions-5.0.json#/definitions/inlineStepType"},
                "description": {"$ref": "#/definitions/stepDescription"},
                "handler": {"$ref": "azure-deviceupdate-manifest-definitions-5.0.json#/definitions/inlineStepHandler"},
                "files": {
                    "type": "array",
                    "title": "Step update files",
                    "description": "Names of update files that agent will pass to handler.",
                    "items": {"$ref": "azure-deviceupdate-manifest-definitions-5.0.json#/definitions/filename"},
                    "minItems": 1,
                    "maxItems": 10,
                },
                "handlerProperties": {
                    "$ref": "azure-deviceupdate-manifest-definitions-5.0.json#/definitions/inlineStepHandlerProperties"
                },
            },
            "additionalProperties": False,
            "required": ["handler", "files"],
        },
        "referenceStep": {
            "type": "object",
            "title": "Reference installation step",
            "description": "Installation instruction step that installs another update.",
            "properties": {
                "type": {"$ref": "azure-deviceupdate-manifest-definitions-5.0.json#/definitions/referenceStepType"},
                "description": {"$ref": "#/definitions/stepDescription"},
                "updateId": {"$ref": "azure-deviceupdate-manifest-definitions-5.0.json#/definitions/updateId"},
            },
            "additionalProperties": False,
            "required": ["type", "updateId"],
        },
    },
    "description": "Schema for import manifest used for importing an update to Device Update for IoT Hub.",
    "properties": {
        "$schema": {"type": "string", "description": "JSON schema reference."},
        "updateId": {"$ref": "azure-deviceupdate-manifest-definitions-5.0.json#/definitions/updateId"},
        "description": {
            "type": "string",
            "title": "Update description",
            "description": "Optional update description.",
            "minLength": 1,
            "maxLength": 512,
        },
        "compatibility": {"$ref": "azure-deviceupdate-manifest-definitions-5.0.json#/definitions/compatibility"},
        "instructions": {"$ref": "#/definitions/instructions"},
        "files": {
            "type": "array",
            "title": "Update files",
            "description": "List of update payload files. Sum of all file sizes may not exceed 2 GB. "
            "May be empty or null if all instruction steps are reference steps.",
            "items": {"$ref": "azure-deviceupdate-manifest-definitions-5.0.json#/definitions/file"},
            "minItems": 0,
            "maxItems": 10,
        },
        "manifestVersion": {
            "type": "string",
            "title": "Import manifest schema version",
            "description": "Import manifest schema version. Must be 5.0.",
            "const": "5.0",
        },
        "createdDateTime": {
            "type": "string",
            "title": "Created date & time",
            "description": "Date & time import manifest was created in ISO 8601 format.",
            "examples": ["2020-10-02T22:18:04.9446744Z"],
        },
    },
    "required": ["updateId", "compatibility", "instructions", "manifestVersion", "createdDateTime"],
    "title": "JSON Schema for Azure Device Update for IoT Hub 'Import Manifest' version 5.0",
    "type": "object",
}

DEVICE_UPDATE_MANIFEST_V5_DEFS = {
    "$id": "https://json.schemastore.org/azure-deviceupdate-manifest-definitions-5.0.json",
    "$schema": "http://json-schema.org/draft-07/schema",
    "definitions": {
        "updateId": {
            "type": "object",
            "title": "Update identity",
            "description": "Unique update identifier.",
            "properties": {
                "provider": {
                    "type": "string",
                    "title": "Update provider",
                    "description": "Entity who is creating or directly responsible for the update. It can be a company name.",
                    "minLength": 1,
                    "maxLength": 64,
                    "pattern": "^[a-zA-Z0-9.-]+$",
                },
                "name": {
                    "type": "string",
                    "title": "Update name",
                    "description": "Identifier for a class of update. It can be a device class or model name.",
                    "minLength": 1,
                    "maxLength": 64,
                    "pattern": "^[a-zA-Z0-9.-]+$",
                },
                "version": {
                    "type": "string",
                    "title": "Update version",
                    "description": "Two to four part dot separated numerical version numbers. Each part must be a number between 0 and 2147483647 and leading zeroes will be dropped.",
                    "pattern": "^\\d+(?:\\.\\d+)+$",
                    "examples": ["1.0", "2021.11.8"],
                },
            },
            "additionalProperties": False,
            "required": ["provider", "name", "version"],
        },
        "compatibility": {
            "type": "array",
            "title": "Update compatibility",
            "description": "List of device property sets this update is compatible with.",
            "items": {"$ref": "azure-deviceupdate-manifest-definitions-5.0.json#/definitions/compatibilityInfo"},
            "minItems": 1,
            "maxItems": 10,
        },
        "compatibilityInfo": {
            "type": "object",
            "title": "Update compatibility info",
            "description": "Properties of a device this update is compatible with.",
            "additionalProperties": {
                "type": "string",
                "minLength": 1,
                "maxLength": 64,
                "propertyNames": {"minLength": 1, "maxLength": 32},
            },
            "minProperties": 1,
            "maxProperties": 5,
        },
        "baseFile": {
            "type": "object",
            "title": "Basic update file information",
            "description": "Update payload file, e.g. binary, firmware, script, etc. Must be unique within update.",
            "properties": {
                "filename": {"$ref": "azure-deviceupdate-manifest-definitions-5.0.json#/definitions/filename"},
                "sizeInBytes": {
                    "type": "number",
                    "title": "File size",
                    "description": "File size in number of bytes.",
                    "minimum": 1,
                },
                "hashes": {"$ref": "azure-deviceupdate-manifest-definitions-5.0.json#/definitions/fileHashes"},
                "properties": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "Optional file properties (not consumed by service but pass-through to device).",
                },
            },
            "required": ["filename", "sizeInBytes", "hashes"],
        },
        "file": {
            "type": "object",
            "title": "Update file",
            "description": "Update payload file, e.g. binary, firmware, script, etc. Must be unique within update.",
            "allOf": [{"$ref": "#/definitions/baseFile"}],
            "properties": {
                "relatedFiles": {
                    "type": "array",
                    "items": {"$ref": "#/definitions/baseFile"},
                    "minItems": 0,
                    "maxItems": 4,
                    "description": "Optional related files metadata used together with DownloadHandler metadata to download payload file.",
                },
                "downloadHandler": {
                    "$ref": "#/definitions/fileDownloadHandler",
                    "description": "Optional download handler for utilizing related files to download payload file.",
                },
            },
        },
        "filename": {
            "type": "string",
            "title": "Update file name",
            "description": "Update payload file name.",
            "minLength": 1,
            "maxLength": 255,
        },
        "fileHashes": {
            "type": "object",
            "title": "File hashes",
            "description": "Base64-encoded file hashes with algorithm name as key. At least SHA-256 algorithm must be specified, and additional algorithm may be specified if supported by agent.",
            "properties": {
                "sha256": {
                    "type": "string",
                    "title": "SHA-256 hash value",
                    "description": "Base64-encoded file hash value using SHA-256 algorithm.",
                }
            },
            "additionalProperties": {"type": "string", "propertyNames": {"maxLength": 10}},
            "maxProperties": 2,
            "required": ["sha256"],
        },
        "fileDownloadHandler": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Download handler identifier.",
                    "pattern": "^\\S+/\\S+:\\d{1,5}$",
                    "minLength": 5,
                    "maxLength": 32,
                    "examples": ["microsoft/delta:1"],
                }
            },
            "required": ["id"],
            "description": "Download handler for utilizing related files to download payload file.",
        },
        "referenceStepType": {
            "type": "string",
            "title": "'Reference' step type",
            "description": "Instruction step type that installs another update.",
            "const": "reference",
        },
        "inlineStepType": {
            "type": "string",
            "title": "'Inline' step type",
            "description": "Instruction step type that performs code execution.",
            "const": "inline",
        },
        "inlineStepHandler": {
            "type": "string",
            "title": "Step handler",
            "description": "Identity of handler on device that can execute this step.",
            "pattern": "^\\S+/\\S+:\\d{1,5}$",
            "minLength": 5,
            "maxLength": 32,
            "examples": ["microsoft/script:1", "microsoft/swupdate:1", "microsoft/apt:1"],
        },
        "inlineStepHandlerProperties": {
            "type": "object",
            "title": "Handler properties",
            "description": "JSON object that agent will pass to handler as arguments.",
            "additionalProperties": True,
        },
    },
    "description": "Shared schema definitions for 'Import Manifest' and 'Update Manifest'.",
    "title": "JSON Schema Definitions for Azure Device Update for IoT Hub Manifests version 5.0",
    "type": "object",
}
