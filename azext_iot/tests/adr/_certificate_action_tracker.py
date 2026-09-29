# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Read-only completion evidence for an owned CA action submitted by the live CLI."""

import re
import logging
from contextlib import contextmanager
from threading import Event, Thread
from time import monotonic, sleep
from unittest.mock import patch
from urllib.parse import urljoin, urlsplit

import requests
from azure.cli.core._profile import Profile
from azure.cli.core.azclierror import AzureResponseError
from azure.core.exceptions import AzureError
from knack.util import CLIError
from urllib3.util import Timeout

from azext_iot.adr.providers.base import _retry_after_seconds
from azext_iot.adr.providers.certificate_activation import ExternalActivationEvidence


def _protect_action_logs():
    # Native SDK pollers can outlive both observe() and fixture cleanup. Keep a
    # URI-only redactor for the process lifetime, without retaining signed URLs.
    # PEM/credential stream redactors must still receive their original boundaries.
    previous = logging.getLogRecordFactory()
    if getattr(previous, "_adr_action_redactor", False):
        return

    def sanitize(text):
        # A Location may be relative, and unknown query names are just as
        # sensitive as "sig".
        text = re.sub(r"""([^\s'"<>?]*/[^\s'"<>?]*\?)[^\s'"<>]+""", r"\1***", text)
        return re.sub(r"""(https?://)[^\s/'"<>@]+@""", r"\1***@", text, flags=re.IGNORECASE)

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        record.msg = sanitize(record.getMessage())
        record.args = ()
        if record.exc_info:
            record.exc_text = sanitize(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = sanitize(record.exc_text)
        if record.stack_info:
            record.stack_info = sanitize(record.stack_info)
        return record

    factory._adr_action_redactor = True
    logging.setLogRecordFactory(factory)


class CertificateActionTracker:
    """Keep acknowledgement URLs only in memory; never render headers, URLs or bodies."""

    def __init__(self, *, resource_id, owned, subscription, endpoint, audience, location,
                 cli_ctx, action="revokeAndRotate", timeout=600, clock=monotonic, sleeper=sleep):
        hosts = {"management.azure.com", "centraluseuap.management.azure.com"}
        endpoint_parts = urlsplit(endpoint)
        prefix = f"/subscriptions/{subscription}/resourceGroups/"
        if (
            resource_id not in owned or not resource_id.casefold().startswith(prefix.casefold())
            or not re.fullmatch(
                r"/subscriptions/[0-9a-fA-F-]+/resourceGroups/[\w.-]+/providers/"
                r"Microsoft.DeviceRegistry/namespaces/[\w.-]+/certificateAuthorities/[\w.-]+",
                resource_id, re.IGNORECASE,
            )
            or endpoint_parts.scheme != "https" or endpoint_parts.netloc not in hosts
            or endpoint_parts.path not in ("", "/") or endpoint_parts.query or endpoint_parts.fragment
            or audience.rstrip("/") != "https://management.azure.com"
            or action not in ("activate", "revokeAndRotate") or timeout <= 0
            or not re.fullmatch(r"[a-z0-9]+", location)
        ):
            raise AssertionError("CA action tracker requires an owned target and approved ARM scope.")
        self.resource_id = resource_id
        self._subscription = subscription
        self._endpoint = endpoint.rstrip("/")
        self._audience = audience
        self._cli_ctx = cli_ctx
        self._action_path = resource_id + "/" + action
        namespace = resource_id.rsplit("/certificateAuthorities/", 1)[0]
        self._regional_scope = f"/subscriptions/{subscription}/providers/Microsoft.DeviceRegistry/locations/{location}"
        self._result_scopes = (
            namespace, resource_id, self._regional_scope,
        )
        self._timeout = timeout
        self._clock = clock
        self._sleep = sleeper
        self._url = None
        self._posts = 0
        self._problem = None
        self._retry_after = None
        self._deadline = None
        self._cleanup_deadline = None
        self._reader = None
        self._activation = None
        self.acknowledgement_status = None
        self.terminal = False
        self.succeeded = False

    def __repr__(self):
        return f"<CertificateActionTracker posts={self._posts} terminal={self.terminal}>"

    def use_activation_resource(self, before, chain, api_version):
        """Select evidence before the POST; never switch after a failed status read."""
        if (
            self._posts or self._deadline is not None or not self._action_path.endswith("/activate")
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:-preview)?", api_version)
        ):
            raise AssertionError("CA activation resource tracking requires pre-submission activation scope.")
        self._activation = ExternalActivationEvidence(before, chain, resource_id=self.resource_id)
        self._url = f"{self._endpoint}{self.resource_id}?api-version={api_version}"

    def _matches(self, request, *, negative=False):
        parts = urlsplit(request.url)
        return (
            request.method.upper() == "POST"
            and parts.scheme == "https" and parts.netloc == urlsplit(self._endpoint).netloc
            and (
                parts.path.casefold() == self._action_path.casefold()
                or (negative and parts.path.rsplit("/", 1)[0].casefold() == self.resource_id.casefold())
            )
            and not parts.fragment
        )

    def _location(self, value):
        if not isinstance(value, str) or not value or any(c.isspace() for c in value) or "\\" in value:
            return None
        try:
            parts = urlsplit(urljoin(self._endpoint + self._action_path, value))
        except ValueError:
            return None
        if (
            parts.scheme != "https" or parts.netloc != urlsplit(self._endpoint).netloc
            or parts.fragment or "%" in parts.path
        ):
            return None
        for scope in self._result_scopes:
            if re.fullmatch(
                re.escape(scope) + r"/operation(?:Results|Statuses)/[a-zA-Z0-9._-]+",
                parts.path, re.IGNORECASE,
            ):
                return parts.geturl()
        if re.fullmatch(
            re.escape(self._regional_scope) + r"/asyncOperationStatuses/[a-zA-Z0-9._-]+",
            parts.path, re.IGNORECASE,
        ):
            return parts.geturl()
        return None

    @contextmanager
    def observe(self, *, negative=False):
        # The original transport sends the real request and returns its response unchanged,
        # including SDK background GETs. Negative cases reject any action POST
        # on the exact owned target, not just the action the command should use.
        _protect_action_logs()
        original = requests.Session.send

        def send(session, request, **kwargs):
            matches = self._matches(request, negative=negative)
            if matches:
                self._posts += 1
                if self._posts != 1:
                    self._problem = "Duplicate owned action POST observed"
                    self.terminal = self.succeeded = False
            response = original(session, request, **kwargs)
            if matches and self._posts == 1:
                self.acknowledgement_status = response.status_code
                self._retry_after = _retry_after_seconds(response, 1)
                if self._activation and response.status_code in (202, 204):
                    pass  # Only the correlated resource GET can complete this tracker.
                elif response.status_code == 204:
                    self.terminal = self.succeeded = True
                elif response.status_code == 202:
                    self._url = self._location(response.headers.get("Location"))
                    if self._url is None:
                        self._problem = "Missing or unsupported owned action Location"
                else:
                    self._problem = f"Untrackable owned action acknowledgement HTTP {response.status_code}"
            return response

        with patch.object(requests.Session, "send", send):
            if self._deadline is None:
                self._deadline = self._clock() + self._timeout
            yield self

    def assert_no_submission(self):
        if self._posts:
            raise AssertionError("Unexpected owned action POST during negative validation; reconciliation/quarantine required.")

    @property
    def submitted(self):
        return self._posts != 0

    def _remaining(self, deadline):
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise AssertionError("Timed out reconciling owned CA action; completion is uncertain.")
        return remaining

    def _fetch(self, deadline, checkpoint):
        checkpoint()
        try:
            # Explicit subscription and ARM audience; never use EmbeddedCLI for credentials.
            token, subscription, _ = Profile(cli_ctx=self._cli_ctx).get_raw_token(
                resource=self._audience, subscription=self._subscription,
            )
        except (CLIError, AzureError, requests.RequestException, ValueError):
            raise AssertionError("Owned CA action authentication failed; credentials suppressed.") from None
        checkpoint()
        remaining = self._remaining(deadline)
        if (
            not isinstance(subscription, str) or subscription.casefold() != self._subscription.casefold()
            or not isinstance(token, tuple) or len(token) < 2 or token[0] != "Bearer" or not token[1]
        ):
            raise AssertionError("Owned CA action authentication returned an unapproved subscription or token type.")
        try:
            with requests.Session() as session:
                checkpoint()
                response = session.get(
                    self._url, headers={"Authorization": f"Bearer {token[1]}"},
                    # Keep ambient netrc credentials from overriding the scoped Profile token.
                    auth=lambda request: request,
                    allow_redirects=False, timeout=Timeout(total=remaining),
                )
        except requests.RequestException:
            raise AssertionError("Owned CA action status GET failed; transport details suppressed.") from None
        checkpoint()
        body = None
        if response.status_code in (200, 202):
            try:
                body = response.json() if response.content else {}
            except ValueError:
                raise AssertionError("Invalid owned CA action status JSON; body suppressed.") from None
        checkpoint()
        return response, body

    def _read(self, deadline):
        if self._reader is not None and self._reader.is_alive():
            raise AssertionError("Previous owned CA action read is still in flight; quarantine required.")
        limit = monotonic() + self._remaining(deadline)
        cancelled, done = Event(), Event()
        result, errors = [], []

        def checkpoint():
            self._remaining(deadline)
            if cancelled.is_set() or monotonic() >= limit:
                raise AssertionError("Timed out reconciling owned CA action; completion is uncertain.")

        def read():
            try:
                result.append(self._fetch(deadline, checkpoint))
            except BaseException as error:  # Only transfer worker failures; never treat them as completion.
                errors.append(error)
            finally:
                done.set()

        # No process timers: works on native Windows and leaves outer pytest
        # absolute/interval timers intact. At most one in-flight read per target.
        self._reader = Thread(target=read, name="adr-ca-status-read", daemon=True)
        self._reader.start()
        try:
            if not done.wait(max(0, limit - monotonic())):
                raise AssertionError("Timed out reconciling owned CA action; completion is uncertain.")
            self._reader.join(max(0, limit - monotonic()))
            checkpoint()
            if errors:
                raise errors[0]
            return result[0]
        finally:
            cancelled.set()

    def _inspect(self, response, body):
        code = response.status_code
        if self._activation and code in (200, 202, 204):
            if code != 200:
                raise AssertionError("CA activation resource GET requires HTTP 200; completion is uncertain.")
            try:
                self.succeeded = self.terminal = self._activation.completed(body)
            except AzureResponseError as error:
                raise AssertionError(str(error)) from None
            return
        if code == 204:
            self.terminal = self.succeeded = True
            return
        if code in (200, 202):
            if not isinstance(body, dict) or not isinstance(body.get("properties", {}), dict):
                raise AssertionError("Invalid owned CA action status shape; body suppressed.")
            states = (body.get("status"), body.get("properties", {}).get("provisioningState"))
            if any(state in ("Failed", "Canceled") for state in states):
                self.terminal = True
                return
            state = states[0] or states[1]
            if code == 200 and state is None and body:
                raise AssertionError("Owned CA action status has no completion evidence; body suppressed.")
            if code == 200 and state in (None, "Succeeded"):
                self.terminal = self.succeeded = True
            return
        # Match ADR Location polling's transient reads, but never replay the action.
        if code not in (404, 408, 429) and code < 500:
            raise AssertionError(f"Owned CA action status GET rejected with HTTP {code}; details suppressed.")

    def wait(self, *, cleanup=False):
        if self._problem or self._posts != 1:
            reason = self._problem or "No exact owned action POST acknowledgement observed"
            raise AssertionError(f"{reason}; quarantine required.")
        if cleanup and self.terminal:
            return
        if cleanup and self._cleanup_deadline is None:
            self._cleanup_deadline = self._clock() + self._timeout
        deadline = self._cleanup_deadline if cleanup else self._deadline
        self._remaining(deadline)
        while not self.terminal:
            if not self._url:
                raise AssertionError("Owned CA action has no tracking URL; quarantine required.")
            remaining = self._remaining(deadline)
            self._sleep(min(self._retry_after or 1, remaining))
            response, body = self._read(deadline)
            self._remaining(deadline)
            self._inspect(response, body)
            self._retry_after = _retry_after_seconds(response, 1)
        if not cleanup and not self.succeeded:
            raise AssertionError("Owned CA action reached terminal Failed/Canceled; service body suppressed.")
