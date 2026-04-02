# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import asyncio
import os
from urllib.parse import unquote, urlparse

from knack.log import get_logger

logger = get_logger(__name__)


def generate_on_start_string(device_id=None):
    device_filter_txt = None
    if device_id:
        device_filter_txt = " filtering on device: {},".format(device_id)

    return "Starting event monitor,{} use ctrl-c to stop...".format(
        device_filter_txt if device_filter_txt else "",
    )


def stop_monitor():
    raise KeyboardInterrupt()


def get_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.get_event_loop()
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop


def unicode_decode(data: bytes, default: str = None):
    for encoding in ["utf-8", "utf-16", "utf-32"]:
        try:
            data = data.decode(encoding)
            break
        except (UnicodeError, UnicodeDecodeError):
            continue
    else:
        data = default

    return data


def extract_message_body(message) -> bytes:
    """
    Extract and materialize message body from EventData.
    Handles different body types: bytes, str, list, or generator.

    Args:
        message: EventData message object

    Returns:
        bytes: The message body as bytes
    """
    body = message.body
    if isinstance(body, bytes):
        return body
    elif isinstance(body, str):
        return body.encode('utf-8')
    elif isinstance(body, list):
        return b''.join(chunk if isinstance(chunk, bytes) else chunk.encode('utf-8') for chunk in body)
    else:
        # body is a generator - consume it
        try:
            chunks = []
            for chunk in body:
                if isinstance(chunk, bytes):
                    chunks.append(chunk)
                elif isinstance(chunk, str):
                    chunks.append(chunk.encode('utf-8'))
                else:
                    chunks.append(str(chunk).encode('utf-8'))
            return b''.join(chunks)
        except Exception:
            return b''


def get_http_proxy_settings():
    """Return EventHub-compatible proxy settings from environment variables."""
    proxy_value = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
    )

    if not proxy_value:
        return None

    parsed = urlparse(proxy_value if "://" in proxy_value else f"http://{proxy_value}")
    if not parsed.hostname or not parsed.port:
        logger.warning(
            "Proxy environment variable is set (%r) but could not be parsed "
            "(hostname or port missing) — proxy will not be used for event monitoring.",
            proxy_value,
        )
        return None

    proxy_scheme = parsed.scheme or "http"
    # proxy_hostname must include the scheme (e.g. "http://host" not "host").
    settings = {
        "proxy_hostname": f"{proxy_scheme}://{parsed.hostname}",
        "proxy_port": parsed.port,
    }

    if parsed.username:
        settings["username"] = unquote(parsed.username)
    if parsed.password:
        settings["password"] = unquote(parsed.password)

    return settings
