# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Release-provider adapters: one argument mapping drives both preview and execution."""

import json
from dataclasses import dataclass

from azext_iot.adr.ui.core.commands import quote
from azext_iot.adr.ui.core.session import SessionError
from azext_iot.adr.ui.core.spec import Action

SCOPE_FLAGS = {"namespace_name": "--ns", "resource_group_name": "-g",
               "certificate_authority_name": "--ca-name", "job_name": "--job-name"}


@dataclass(frozen=True)
class Field:
    key: str
    flag: str
    label: str
    default: str = ""
    choices: tuple = ()
    optional: bool = False

    def current(self, payload):
        if self.key == "tags":
            return json.dumps(payload.get("tags") or {})
        properties = payload.get("properties", {})
        if self.key == "validity_days":
            value = properties.get("certificate", {}).get("validityPeriodInDays")
        else:
            key = {"enablement_state": "enablementState", "display_name": "displayName"}.get(self.key, self.key)
            value = properties.get(key)
        return str(value) if value is not None else ""

    def parse(self, text):
        text = text.strip()
        if not text:
            if self.optional:
                return None
            raise ValueError(f"{self.label} is required.")
        if self.choices and text not in self.choices:
            raise ValueError(f"{self.label}: choose {', '.join(self.choices)}.")
        if self.key == "validity_days":
            if not text.isdigit() or not 1 <= int(text) <= 90:
                raise ValueError("Validity must be an integer from 1 to 90 days.")
            return int(text)
        if self.key == "tags":
            tags = json.loads(text)
            if not isinstance(tags, dict) or any(
                not isinstance(value, str) for value in tags.values()
            ):
                raise ValueError("Tags must be a JSON object with string values.")
            return tags
        return text


NAME = Field("name", "-n", "Name")
TAGS = Field("tags", "--tags", 'Replace tags (JSON object; {} clears all tags)', "{}")
VALIDITY = Field("validity_days", "--validity-days", "Validity days (1–90)", "30")
NS_SCOPE = ("namespace_name", "resource_group_name")


def provider_action(provider, command, method, name_key, scope_keys=NS_SCOPE, fields=(),
                    label=None, note="", destructive=False, collection=False,
                    applies_to=None, no_wait=True, unavailable="Not applicable to this resource."):
    """Call only the declared provider method, never parse or execute shell input."""
    def arguments(scope, payload):
        values = payload.get("_inputs", {})
        args = {key: scope[key] for key in scope_keys}
        args[name_key] = values.get("name") if collection else payload["name"]
        args.update({field.key: values[field.key] for field in fields
                     if field.key != "name" and values.get(field.key) is not None})
        return args

    def preview(scope, payload):
        args = arguments(scope, payload)
        flags = dict(SCOPE_FLAGS, **{name_key: "-n"})
        flags.update({field.key: field.flag for field in fields if field.key != "name"})
        parts = ["az", command, "--subscription", quote(scope["subscription_id"])]
        for key, value in args.items():
            parts.append(flags[key])
            if key == "tags":
                parts.extend(quote(f"{key}={val}") for key, val in value.items())
                if not value:
                    parts.append("''")
            else:
                parts.append(quote(value))
        if destructive:
            parts.append("--yes")
        return " ".join(parts)

    def invoke(session, scope, payload):
        if session.read_only:
            raise SessionError("Read-only session: writes are disabled.")
        if scope.get("subscription_id") != session.scope.subscription_id:
            raise SessionError("Subscription changed. Review the action again.")
        args = arguments(scope, payload)
        target = session.provider(provider)
        read_args = {key: args[key] for key in (*scope_keys, name_key)}
        if collection:
            try:
                session.call(target.show, **read_args)
            except SessionError as error:
                if error.status_code != 404:
                    raise
            else:
                raise SessionError("The resource already exists. Refresh and use Update; Create will not replace it.")
        else:
            current = session.call(target.show, **read_args)
            if payload.get("etag") and current.get("etag") != payload["etag"]:
                raise SessionError("Resource changed since review. Refresh and review again.")
            if applies_to and not applies_to(current):
                raise SessionError(unavailable)
        if no_wait:
            args["no_wait"] = True
        return session.call(getattr(target, method), **args)

    return Action(
        name=method, label=label or method.capitalize(), destructive=destructive,
        collection=collection, fields=fields, command=command, note=note,
        applies_to=applies_to, preview=preview, invoke=invoke, unavailable=unavailable,
    )


def crud(provider, command, name_key, scope_keys=NS_SCOPE, create_fields=None, update_fields=(TAGS,),
         no_wait=True):
    actions = []
    if create_fields is not None:
        actions.append(provider_action(
            provider, f"{command} create", "create", name_key, scope_keys,
            fields=(NAME, *create_fields), collection=True, no_wait=no_wait,
            note="Create a resource. Existing names are never replaced. Provider defaults apply.",
        ))
    if update_fields:
        actions.append(provider_action(
            provider, f"{command} update", "update", name_key, scope_keys,
            fields=update_fields, no_wait=no_wait, note="Update only the fields supplied in this form.",
        ))
    actions.append(provider_action(
        provider, f"{command} delete", "delete", name_key, scope_keys, destructive=True,
        no_wait=no_wait, note="Delete this resource. This cannot be undone. Related resources are not cleaned up.",
    ))
    return tuple(actions)
