# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Kind registration.

Adding a resource kind means adding a module here and one line to ``_BUILDERS``.
Nothing in ``core``, ``screens`` or ``widgets`` changes.
"""

from typing import Callable, List

from azext_iot.adr.ui.core.spec import Registry, ResourceSpec
from azext_iot.adr.ui.kinds import certificate, device, group, job, link, namespace

#: Builders in registration order. Roots first, so the application opens on a namespace
#: list; each builder takes a session and returns one spec.
_BUILDERS: List[Callable[[object], ResourceSpec]] = [
    namespace.build,
    device.build,
    device.build_auth,
    device.build_attribute,
    device.build_capability,
    group.build,
    group.build_member,
    job.build,
    job.build_run,
    link.build,
    certificate.build_ca,
    certificate.build_policy,
    certificate.build_update_instance,
]


def build_registry(session) -> Registry:
    """Register every kind against ``session`` and return the registry."""
    registry = Registry()
    for builder in _BUILDERS:
        registry.register(builder(session))
    return registry
