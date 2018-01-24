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
