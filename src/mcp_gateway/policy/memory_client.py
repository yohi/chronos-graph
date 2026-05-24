from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast
from urllib.parse import urlsplit

from mcp_gateway.policy.models_evaluator import MemoryItem

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger("chronos_evaluator.memory")

_DEFAULT_ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class MemoryFetchError(Exception):
    pass


@dataclass(slots=True)
class MemoryClient:
    dashboard_url: str
    timeout_seconds: float = 3.0
    top_k: int = 5
    _api_key: str | None = field(default=None, repr=False)
    _allowed_hosts: frozenset[str] = field(default=_DEFAULT_ALLOWED_HOSTS, repr=False)
    _client: httpx.AsyncClient | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.dashboard_url = self.dashboard_url.rstrip("/")
        _validate_dashboard_url(self.dashboard_url, self._allowed_hosts)

    @classmethod
    def from_env(cls) -> MemoryClient | None:
        url = os.getenv("CHRONOS_DASHBOARD_URL")
        if not url:
            return None

        try:
            timeout_seconds = float(os.getenv("CHRONOS_DASHBOARD_TIMEOUT_SECONDS", "3.0"))
            if timeout_seconds <= 0:
                raise MemoryFetchError("CHRONOS_DASHBOARD_TIMEOUT_SECONDS must be > 0")

            top_k = int(os.getenv("CHRONOS_DASHBOARD_TOP_K", "5"))
            if top_k <= 0:
                raise MemoryFetchError("CHRONOS_DASHBOARD_TOP_K must be > 0")
        except (ValueError, TypeError) as exc:
            raise MemoryFetchError(f"invalid numeric value in environment: {exc}") from exc

        return cls(
            dashboard_url=url,
            timeout_seconds=timeout_seconds,
            top_k=top_k,
            _api_key=os.getenv("CHRONOS_DASHBOARD_API_KEY"),
            _allowed_hosts=_allowed_hosts_from_env(),
        )

    def _get_client(self) -> httpx.AsyncClient:
        import httpx

        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds),
                transport=self._build_transport(),
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _build_transport(self) -> httpx.AsyncBaseTransport | None:
        return None

    async def retrieve(self, query: str, project: str | None = None) -> list[MemoryItem]:
        import httpx

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        http = self._get_client()

        try:
            response = await http.post(
                f"{self.dashboard_url}/api/memories/semantic-search",
                json={"query": query, "project": project, "top_k": self.top_k},
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise MemoryFetchError("dashboard request timed out") from exc
        except httpx.HTTPError as exc:
            raise MemoryFetchError(f"dashboard request failed: {type(exc).__name__}") from exc

        if response.status_code != 200:
            raise MemoryFetchError(f"dashboard returned status {response.status_code}")

        try:
            data = cast(object, response.json())
        except (ValueError, UnicodeDecodeError) as exc:
            raise MemoryFetchError(f"invalid JSON from dashboard: {exc}") from exc

        if not isinstance(data, list):
            raise MemoryFetchError(f"expected list, got {type(data).__name__}")

        items: list[MemoryItem] = []
        for item in cast(list[object], data):
            if not isinstance(item, Mapping):
                logger.warning("skipping malformed memory item: non-object")
                continue
            memory = cast(Mapping[str, object], item)
            try:
                # content must be strictly str
                content = memory.get("content")
                if not isinstance(content, str):
                    logger.warning("skipping malformed memory item: content must be str")
                    continue

                # memory_type should be str or None
                raw_type_alt = memory.get("memoryType")
                raw_type_fallback = memory.get("memory_type")
                raw_type = raw_type_alt if raw_type_alt is not None else raw_type_fallback

                if raw_type is not None and not isinstance(raw_type, str):
                    logger.warning("skipping malformed memory item: memory_type must be str")
                    continue
                memory_type = raw_type or ""

                importance_value = memory.get("importance")
                if not isinstance(importance_value, (int, float, str)):
                    importance_value = 0.0

                items.append(
                    MemoryItem(
                        content=content,
                        memory_type=memory_type,
                        importance=float(importance_value),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("skipping malformed memory item: %s", exc)
        return items


def _allowed_hosts_from_env() -> frozenset[str]:
    raw = os.getenv("CHRONOS_DASHBOARD_ALLOWED_HOSTS")
    if not raw:
        return _DEFAULT_ALLOWED_HOSTS
    parsed = frozenset(host.strip().lower() for host in raw.split(",") if host.strip())
    return parsed if parsed else _DEFAULT_ALLOWED_HOSTS


def _validate_dashboard_url(url: str, allowed_hosts: frozenset[str]) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        raise MemoryFetchError("dashboard URL must use http or https")
    if parsed.username or parsed.password:
        raise MemoryFetchError("dashboard URL must not include userinfo")
    host = (parsed.hostname or "").lower()
    if not host:
        raise MemoryFetchError("dashboard URL must include a host")
    if host not in allowed_hosts:
        raise MemoryFetchError("dashboard URL host is not allowed")
