"""Thin Maximo Manage REST client: auth, paging, retries and clear errors.

Only this module imports ``requests``.  Checks, KPIs, the report and even the
loader talk to a :class:`mxbess.repository.Repository`, which keeps the offline
work testable and gives the CSV fallback an identical surface.

Every assumption about the wire format is marked UNVERIFIED in
:mod:`mxbess.mapping` and ``docs/instance-notes.md`` until Phase 0 confirms it.
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urljoin

import requests

from .mapping import OBJECT_STRUCTURES

logger = logging.getLogger("mxbess.client")

_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
_MAX_PAGES = 1000


class MaximoError(RuntimeError):
    """Base class for all client failures."""


class MaximoConnectionError(MaximoError):
    """The host could not be reached (after retries)."""


class MaximoHTTPError(MaximoError):
    """A non-success HTTP response that is not one of the specific subclasses."""

    def __init__(self, status: int, url: str, detail: str = "") -> None:
        self.status = status
        self.url = url
        self.detail = detail
        message = f"Maximo returned HTTP {status} for {url}"
        if detail:
            message += f": {detail}"
        super().__init__(message)


class AuthenticationError(MaximoHTTPError):
    """HTTP 401/403 - the key is absent, wrong, or lacks access."""


class NotFoundError(MaximoHTTPError):
    """HTTP 404 - the object structure or record does not exist."""


class ValidationError(MaximoHTTPError):
    """HTTP 400/422 - Maximo rejected the request payload."""


class MaximoClient:
    """Small synchronous client for MAS Manage's JSON object-structure API."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 30.0,
        max_retries: int = 4,
        backoff_seconds: float = 0.5,
        page_size: int = 100,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        object_structures: dict[str, str] | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key must not be empty")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.page_size = page_size
        self._session = session or requests.Session()
        self._sleep = sleep
        self._object_structures = dict(object_structures or OBJECT_STRUCTURES)
        self._session.headers.update(
            {
                "apikey": api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def __repr__(self) -> str:
        return f"MaximoClient(base_url={self.base_url!r}, timeout={self.timeout!r})"

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> MaximoClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------ URLs
    def object_url(self, kind: str) -> str:
        """Return the collection URL for a model kind or raw object-structure name."""
        os_name = self._object_structures.get(kind, kind)
        return f"{self.base_url}/api/os/{os_name}"

    def record_url(self, kind: str, key: str) -> str:
        return f"{self.object_url(kind)}/{quote(str(key), safe='')}"

    # --------------------------------------------------------------- public API
    def get_all(
        self,
        kind: str,
        *,
        where: str | None = None,
        select: str | None = None,
        page_size: int | None = None,
    ) -> list[dict[str, Any]]:
        """Read every page of an object-structure collection."""
        params: dict[str, Any] = {"oslc.pageSize": page_size or self.page_size}
        if where:
            params["oslc.where"] = where
        if select:
            params["oslc.select"] = select

        url: str | None = self.object_url(kind)
        members: list[dict[str, Any]] = []
        pages = 0
        while url:
            pages += 1
            if pages > _MAX_PAGES:
                raise MaximoError(f"paging exceeded {_MAX_PAGES} pages for {kind}")
            response = self._request("GET", url, params=params)
            payload = response.json() if response.content else {}
            if isinstance(payload, list):
                members.extend(payload)
                break
            if not isinstance(payload, dict):  # pragma: no cover - defensive
                raise MaximoError(f"unexpected response shape for {kind}: {type(payload)}")
            batch = payload.get("member") or payload.get("rdfs:member") or []
            if not isinstance(batch, list):  # pragma: no cover - defensive
                raise MaximoError(f"unexpected member shape for {kind}")
            members.extend(batch)
            url = self._next_page_url(payload, response, url)
            params = {}  # the next-page href already carries the query string
        return members

    def get_one(self, kind: str, key: str) -> dict[str, Any]:
        response = self._request("GET", self.record_url(kind, key))
        return response.json() if response.content else {}

    def create(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request("POST", self.object_url(kind), json=payload)
        return response.json() if response.content else {}

    def update(self, kind: str, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        """PATCH a record.  VERIFY: partial update support on the trial instance."""
        response = self._request("PATCH", self.record_url(kind, key), json=payload)
        return response.json() if response.content else {}

    def find_one_by_key(self, kind: str, where: str) -> dict[str, Any] | None:
        records = self.get_all(kind, where=where, page_size=2)
        return records[0] if records else None

    # ---------------------------------------------------------------- internals
    @staticmethod
    def _next_page_url(
        payload: dict[str, Any], response: requests.Response, current_url: str
    ) -> str | None:
        response_info = payload.get("responseInfo")
        if isinstance(response_info, dict):
            next_page = response_info.get("nextPage")
            if isinstance(next_page, dict) and next_page.get("href"):
                return urljoin(current_url, str(next_page["href"]))
        # Fallback for servers that emit an OSLC Link header instead.
        link_header = response.headers.get("Link", "")
        for part in link_header.split(","):
            segments = [segment.strip() for segment in part.split(";")]
            if segments and segments[0].startswith("<") and 'rel="next"' in part:
                return urljoin(current_url, segments[0].strip("<>"))
        return None

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                logger.debug("%s %s (attempt %d)", method, url, attempt + 1)
                response = self._session.request(
                    method, url, params=params, json=json, timeout=self.timeout
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                self._wait(attempt, None)
                continue

            status = response.status_code
            logger.debug("%s %s -> %d", method, url, status)
            if 200 <= status < 300:
                return response
            if status in {401, 403}:
                raise AuthenticationError(status, url, _error_detail(response))
            if status == 404:
                raise NotFoundError(status, url, _error_detail(response))
            if status in {400, 422}:
                raise ValidationError(status, url, _error_detail(response))
            if status in _RETRYABLE_STATUSES:
                last_error = MaximoHTTPError(status, url, _error_detail(response))
                if attempt < self.max_retries:
                    self._wait(attempt, response.headers.get("Retry-After"))
                    continue
                raise last_error
            raise MaximoHTTPError(status, url, _error_detail(response))

        raise MaximoConnectionError(
            f"Maximo host unreachable after {self.max_retries + 1} attempts: {url}"
        ) from last_error

    def _wait(self, attempt: int, retry_after: str | None) -> None:
        delay = self.backoff_seconds * (2**attempt)
        if retry_after:
            with contextlib.suppress(ValueError):
                delay = max(0.0, float(retry_after))
        delay = min(delay, 60.0)
        if delay > 0:
            self._sleep(delay)


def _error_detail(response: requests.Response) -> str:
    """Extract a short, safe error message; never include request headers."""
    try:
        payload = response.json()
    except ValueError:
        return (response.text or "")[:300]
    if isinstance(payload, dict):
        for key in ("Error", "error", "message", "detail", "ErrorDescription"):
            value = payload.get(key)
            if value:
                return str(value)[:300]
    return str(payload)[:300]
