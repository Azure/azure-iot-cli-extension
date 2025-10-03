# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from enum import Enum
from collections import deque

from knack.log import get_logger
from azext_iot.common.utility import process_json_arg

from jsonschema import Draft4Validator, Draft7Validator


logger = get_logger(__name__)


class JsonSchemaType(Enum):
    """
    Type of configuration deployment.
    """

    draft4 = "draft4"
    draft7 = "draft7"


class JsonSchemaValidator(object):
    def __init__(self, schema, schema_type):
        self.schema = schema
        self.schema_type = schema_type
        self.errors = []

    def _add_error(self, error_msg, content_path, schema_path):
        if isinstance(content_path, deque):
            content_path = ".".join(map(str, list(content_path)))
        if isinstance(schema_path, deque):
            schema_path = ".".join(map(str, list(schema_path)))
        e = {
            "description": error_msg,
            "contentPath": content_path,
            "schemaPath": schema_path,
        }
        self.errors.append(e)

    def _get_validator(self):
        if self.schema_type == JsonSchemaType.draft4:
            return Draft4Validator(self.schema)
        if self.schema_type == JsonSchemaType.draft7:
            return Draft7Validator(self.schema)
        return None

    def validate(self, content):
        if isinstance(content, str):
            content = process_json_arg(content, argument_name="content")

        validator = self._get_validator()

        if not validator:
            logger.info("Json schema type not supported, skipping validation...")
            return self.errors

        try:
            for error in sorted(validator.iter_errors(content), key=str):
                self._add_error(error.message, error.path, error.schema_path)
        except Exception:
            logger.info("Invalid json schema, skipping validation...")

        return self.errors
