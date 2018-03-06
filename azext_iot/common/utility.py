# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
utility: Define helper functions for 'common' scripts.

"""

import os
import sys
import contextlib
import ast
import json
from threading import Thread, Event


@contextlib.contextmanager
def block_stdout():
    """
    This function blocks IoT SDK C output. Non-intrusive due to context.
    """
    devnull = open(os.devnull, 'w')
    orig_stdout_fno = os.dup(sys.stdout.fileno())
    os.dup2(devnull.fileno(), 1)
    try:
        yield
    finally:
        os.dup2(orig_stdout_fno, 1)
        devnull.close()


def parse_entity(iothub_device):
    """
    Function creates a dict of device properties.

    Args:
        iothub_device (object): object to extract attributes from.

    Returns:
        device (dict): a dictionary of properties from the function input.
    """
    device = {}
    attributes = [attr for attr in dir(iothub_device) if not attr.startswith('__')]
    for attribute in attributes:
        device[attribute] = str(getattr(iothub_device, attribute, None))
    return device


# pylint: disable=broad-except
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


def validate_key_value_pairs(string):
    """
    Funtion to validate key-value pairs in the format: a=b;c=d

    Args:
        string (str): semicolon delimited string of key/value pairs.

    Returns (dict, None): a dictionary of key value pairs.
    """
    result = None
    if string:
        kv_list = [x for x in string.split(';') if '=' in x]     # key-value pairs
        result = dict(x.split('=', 1) for x in kv_list)
    return result


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
        except Exception:
            raise json_ex


def execute_onthread(**kwargs):
    """
    Experimental generic helper for executing methods without return values on a background thread

    Args:
        kwargs: Supported kwargs are 'interval' (int) to specify intervals between calls,
                'method' (func) to specify method pointer for execution,
                'args' (list) to specify method arguments,
                'max_runs' (int) indicate an upper bound on number of executions,
                'return_handle' (bool) indicates whether to return a Thread handle

    Returns:
        Event(): Object to set the event cancellation flag
        or if 'return_handle'=True
        Event(), Thread(): Event object to set the cancellation flag, Executing Thread object
    """

    interval = kwargs.get('interval')
    method = kwargs.get('method')
    args = kwargs.get('args')
    max_runs = kwargs.get('max_runs')
    handle = kwargs.get('return_handle')

    if not interval:
        interval = 2
    if not method:
        raise ValueError('kwarg "method" required for execution')
    if not args:
        args = []

    cancellation_token = Event()

    def method_wrap(max_runs=None):
        runs = 0
        while not cancellation_token.wait(interval):
            if max_runs:
                if runs >= max_runs:
                    break
            method(*args)
            runs += 1

    op = Thread(target=method_wrap, args=(max_runs,))
    op.start()

    if handle:
        return cancellation_token, op

    return cancellation_token
