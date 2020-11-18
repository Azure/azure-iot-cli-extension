# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
utility: Defines common utility functions and components.

"""

import ast
import base64
import isodate
import json
import os
import sys
import re
import hmac
import hashlib
import random

from threading import Event, Thread
from datetime import datetime
from knack.log import get_logger
from knack.util import CLIError

logger = get_logger(__name__)


def parse_entity(entity, filter_none=False):
    """
    Function creates a dict of object attributes.

    Args:
        entity (object): object to extract attributes from.

    Returns:
        result (dict): a dictionary of attributes from the function input.
    """
    result = {}
    attributes = [attr for attr in dir(entity) if not attr.startswith("_")]
    for attribute in attributes:
        value = getattr(entity, attribute, None)
        if filter_none and not value:
            continue
        value_behavior = dir(value)
        if "__call__" not in value_behavior:
            result[attribute] = value
    return result


def evaluate_literal(literal, expected):
    """
    Function to provide safe evaluation of code literal.

    Args:
        literal (): code literal
        expected (class, type, tuple): expected resulting class,
            type or tuple of literal evaluation.

    Returns:
        result (string, number, tuple, list, dict, boolean, None).
    """
    # Safe evaluation
    try:
        result = ast.literal_eval(literal)
        if not isinstance(result, expected):
            return None
        return result
    except Exception:
        return None


def verify_transform(subject, mapping):
    """
    Determines if a key from mapping exists in subject and if so
    verifies that subject[k] is of type mapping[k]
    """
    import jmespath

    for k in mapping.keys():
        result = jmespath.search(k, subject)

        if result is None:
            raise AttributeError('The property "{}" is required'.format(k))
        if not isinstance(result, mapping[k]):
            supplemental_info = ""
            if mapping[k] == dict:
                wiki_link = "https://github.com/Azure/azure-iot-cli-extension/wiki/Tips"
                supplemental_info = "Review inline JSON examples here --> {}".format(
                    wiki_link
                )

            raise TypeError(
                'The property "{}" must be of {} but is {}. Input: {}. {}'.format(
                    k, str(mapping[k]), str(type(result)), result, supplemental_info
                )
            )


def validate_key_value_pairs(string):
    """
    Funtion to validate key-value pairs in the format: a=b;c=d

    Args:
        string (str): semicolon delimited string of key/value pairs.

    Returns (dict, None): a dictionary of key value pairs.
    """
    result = None
    if string:
        kv_list = [x for x in string.split(";") if "=" in x]  # key-value pairs
        result = dict(x.split("=", 1) for x in kv_list)
    return result


def process_json_arg(content, argument_name, preserve_order=False):
    """ Primary processor of json input """

    json_from_file = None

    if os.path.exists(content):
        json_from_file = content
        content = read_file_content(content)

    try:
        return shell_safe_json_parse(content, preserve_order)
    except CLIError as ex:
        if looks_like_file(content):
            logger.warning(
                "The json payload for argument '%s' looks like its intended from a file. "
                "Please ensure the file path is correct.",
                argument_name,
            )

        file_content_error = "from file: '{}' ".format(json_from_file)
        raise CLIError(
            "Failed to parse json {}for argument '{}' with exception:\n    {}".format(
                file_content_error if json_from_file else "", argument_name, ex
            )
        )


def shell_safe_json_parse(json_or_dict_string, preserve_order=False):
    """ Allows the passing of JSON or Python dictionary strings. This is needed because certain
    JSON strings in CMD shell are not received in main's argv. This allows the user to specify
    the alternative notation, which does not have this problem (but is technically not JSON). """
    try:
        if not preserve_order:
            return json.loads(json_or_dict_string)
        from collections import OrderedDict

        return json.loads(json_or_dict_string, object_pairs_hook=OrderedDict)
    except ValueError as json_ex:
        try:
            return ast.literal_eval(json_or_dict_string)
        except SyntaxError:
            raise CLIError(json_ex)
        except ValueError as ex:
            logger.debug(
                ex
            )  # log the exception which could be a python dict parsing error.
            raise CLIError(
                json_ex
            )  # raise json_ex error which is more readable and likely.


def read_file_content(file_path, allow_binary=False):
    from codecs import open as codecs_open

    # Note, always put 'utf-8-sig' first, so that BOM in WinOS won't cause trouble.
    for encoding in ["utf-8-sig", "utf-8", "utf-16", "utf-16le", "utf-16be"]:
        try:
            with codecs_open(file_path, encoding=encoding) as f:
                logger.debug("Attempting to read file %s as %s", file_path, encoding)
                return f.read()
        except (UnicodeError, UnicodeDecodeError):
            pass

    if allow_binary:
        try:
            with open(file_path, "rb") as input_file:
                logger.debug("Attempting to read file %s as binary", file_path)
                return base64.b64encode(input_file.read()).decode("utf-8")
        except Exception:  # pylint: disable=broad-except
            pass
    raise CLIError("Failed to decode file {} - unknown decoding".format(file_path))


def trim_from_start(s, substring):
    """ Trims a substring from the target string (if it exists) returning the trimmed string.
    Otherwise returns original target string. """
    if s.startswith(substring):
        s = s[len(substring) :]
    return s


def validate_min_python_version(major, minor, error_msg=None, exit_on_fail=True):
    """ If python version does not match AT LEAST requested values, will throw non 0 exit code."""
    version = sys.version_info
    result = False
    if version.major > major:
        return True
    if major == version.major:
        result = version.minor >= minor

    if not result:
        if exit_on_fail:
            msg = (
                error_msg
                if error_msg
                else "Python version {}.{} or higher required for this functionality.".format(
                    major, minor
                )
            )
            sys.exit(msg)

    return result


def unicode_binary_map(target):
    """ Decode binary keys and values of map to unicode."""
    # Assumes no iteritems()
    result = {}

    for k in target:
        key = k
        if isinstance(k, bytes):
            key = str(k, "utf8")

        if isinstance(target[k], bytes):
            result[key] = str(target[k], "utf8")
        else:
            result[key] = target[k]

    return result


def execute_onthread(**kwargs):
    """
    Experimental generic helper for executing methods without return values on a background thread

    Args:
        kwargs: Supported kwargs are 'interval' (int) to specify intervals between calls
                'method' (func) to specify method pointer for execution
                'args' (list) to specify method arguments
                'max_runs' (int) indicate an upper bound on number of executions
                'return_handle' (bool) indicates whether to return a Thread handle

    Returns:
        Event(): Object to set the event cancellation flag
        or if 'return_handle'=True
        Event(), Thread(): Event object to set the cancellation flag, Executing Thread object
    """

    interval = kwargs.get("interval")
    method = kwargs.get("method")
    method_args = kwargs.get("args")
    max_runs = kwargs.get("max_runs")
    handle = kwargs.get("return_handle")

    if not interval:
        interval = 2
    if not method:
        raise ValueError('kwarg "method" required for execution')
    if not method_args:
        method_args = []

    cancellation_token = Event()

    def method_wrap(max_runs=None):
        runs = 0
        while not cancellation_token.wait(interval):
            if max_runs:
                if runs >= max_runs:
                    break
            method(*method_args)
            runs += 1

    op = Thread(target=method_wrap, args=(max_runs,))
    op.start()

    if handle:
        return cancellation_token, op

    return cancellation_token


def url_encode_dict(d):
    try:
        from urllib import urlencode
    except ImportError:
        from urllib.parse import urlencode

    return urlencode(d)


def url_encode_str(s, plus=False):
    try:
        if plus:
            from urllib import quote_plus
        else:
            from urllib import quote
    except ImportError:
        if plus:
            from urllib.parse import quote_plus
        else:
            from urllib.parse import quote

    return quote_plus(s) if plus else quote(s)


def test_import(package):
    """ Used to determine if a dependency is loading correctly """
    import importlib

    try:
        importlib.import_module(package)
    except ImportError:
        return False
    return True


def unpack_pnp_http_error(e):
    error = unpack_msrest_error(e)
    if isinstance(error, dict):
        if error.get("error"):
            error = error["error"]
        if error.get("stackTrace"):
            error.pop("stackTrace")
    return error


def unpack_msrest_error(e):
    """ Obtains full response text from an msrest error """

    op_err = None
    try:
        op_err = json.loads(e.response.text)
    except (ValueError, TypeError):
        op_err = e.response.text
    if not op_err:
        return str(e)
    return op_err


def dict_transform_lower_case_key(d):
    """ Converts a dictionary to an identical one with all lower case keys """
    return {k.lower(): v for k, v in d.items()}


def calculate_millisec_since_unix_epoch_utc():
    now = datetime.utcnow()
    epoch = datetime.utcfromtimestamp(0)
    return int(1000 * (now - epoch).total_seconds())


def init_monitoring(cmd, timeout, properties, enqueued_time, repair, yes):
    from azext_iot.common.deps import ensure_uamqp
    from knack.util import CLIError

    validate_min_python_version(3, 5)

    if timeout < 0:
        raise CLIError("Monitoring timeout must be 0 (inf) or greater.")
    timeout = timeout * 1000

    config = cmd.cli_ctx.config
    output = cmd.cli_ctx.invocation.data.get("output", None)
    if not output:
        output = "json"
    ensure_uamqp(config, yes, repair)

    if not properties:
        properties = []
    properties = set((key.lower() for key in properties))

    if not enqueued_time:
        enqueued_time = calculate_millisec_since_unix_epoch_utc()
    return (enqueued_time, properties, timeout, output)


def get_sas_token(target):
    from azext_iot.common.digitaltwin_sas_token_auth import (
        DigitalTwinSasTokenAuthentication,
    )

    token = ""
    if target.get("repository_id"):
        token = DigitalTwinSasTokenAuthentication(
            target["repository_id"],
            target["entity"],
            target["policy"],
            target["primarykey"],
        ).generate_sas_token()
    return {"Authorization": "{}".format(token)}


def dict_clean(d):
    """ Remove None from dictionary """
    if not isinstance(d, dict):
        return d
    return dict((k, dict_clean(v)) for k, v in d.items() if v is not None)


def looks_like_file(element):
    element = element.lower()
    return element.endswith(
        (
            ".log",
            ".rtf",
            ".txt",
            ".json",
            ".yaml",
            ".yml",
            ".md",
            ".rst",
            ".doc",
            ".docx",
            ".html",
            ".htm",
            ".py",
            ".java",
            ".ts",
            ".js",
            ".cs",
        )
    )


def ensure_pkg_resources_entries():
    import pkg_resources

    from azure.cli.core.extension import get_extension_path
    from azext_iot.constants import EXTENSION_NAME

    extension_path = get_extension_path(EXTENSION_NAME)
    if extension_path not in pkg_resources.working_set.entries:
        pkg_resources.working_set.add_entry(extension_path)

    return


class ISO8601Validator:
    def is_iso8601_date(self, to_validate) -> bool:
        try:
            return bool(isodate.parse_date(to_validate))
        except Exception:
            return False

    def is_iso8601_datetime(self, to_validate: str) -> bool:
        try:
            return bool(isodate.parse_datetime(to_validate))
        except Exception:
            return False

    def is_iso8601_duration(self, to_validate: str) -> bool:
        try:
            return bool(isodate.parse_duration(to_validate))
        except Exception:
            return False

    def is_iso8601_time(self, to_validate: str) -> bool:
        try:
            return bool(isodate.parse_time(to_validate))
        except Exception:
            return False


def ensure_min_version(cur_ver, min_ver):
    from pkg_resources._vendor.packaging import version

    return version.parse(cur_ver) >= version.parse(min_ver)


def scantree(path):
    for entry in os.scandir(path):
        if entry.is_dir(follow_symlinks=False):
            yield from scantree(entry.path)
        else:
            yield entry


def find_between(s, start, end):
    return (s.split(start))[1].split(end)[0]


def valid_hostname(host_name):
    """
    Approximate validation
    Reference: https://en.wikipedia.org/wiki/Hostname
    """

    if len(host_name) > 253:
        return False

    valid_label = re.compile(r"(?!-)[A-Z\d-]{1,63}(?<!-)$", re.IGNORECASE)
    label_parts = host_name.split(".")
    return all(valid_label.match(label) for label in label_parts)


def compute_device_key(primary_key, registration_id):
    """
    Compute device SAS key
    Args:
        primary_key: Primary group SAS token to compute device keys
        registration_id: Registration ID is alphanumeric, lowercase, and may contain hyphens.
    Returns:
        device key
    """
    secret = base64.b64decode(primary_key)
    device_key = base64.b64encode(
        hmac.new(
            secret, msg=registration_id.encode("utf8"), digestmod=hashlib.sha256
        ).digest()
    )
    return device_key


def generate_key(byte_length=32):
    key = ""
    while byte_length > 0:
        key += chr(random.randrange(1, 128))
        byte_length -= 1
    return base64.b64encode(key.encode()).decode("utf-8")
