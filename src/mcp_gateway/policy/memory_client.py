from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from mcp_gateway.policy.models_evaluator import MemoryItem

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger("chronos_evaluator.memory")


class MemoryFetchError(Exception):
    pass


@dataclass(slots=True)
class MemoryClient:
    dashboard_url: str
    timeout_seconds: float = 3.0
    top_k: int = 5
    _api_key: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> MemoryClient | None:
        url = os.getenv("CHRONOS_DASHBOARD_URL")
        if not url:
            return None
        return cls(
            dashboard_url=url.rstrip("/"),
            timeout_seconds=float(os.getenv("CHRONOS_DASHBOARD_TIMEOUT_SECONDS", "3.0")),
            top_k=int(os.getenv("CHRONOS_DASHBOARD_TOP_K", "5")),
            _api_key=os.getenv("CHRONOS_DASHBOARD_API_KEY"),
        )

    def _build_transport(self) -> "httpx.AsyncBaseTransport | None":
        return None

    async def retrieve(self, query: str, project: str | None = None) -> list[MemoryItem]:
        import httpx

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        transport = self._build_transport()

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds),
                transport=transport,
            ) as http:
                response = await http.post(
                    f"{self.dashboard_url}/api/memories/semantic-search",
                    json={"query": query, "project": project, "top_k": self.top_k},
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise MemoryFetchError(f"dashboard request failed: {exc}") from exc

        if response.status_code != 200:
            raise MemoryFetchError(
                f"dashboard returned {response.status_code}: {response.text[:200]}"
            )

        try:
            data = cast(object, response.json())
        except ValueError as exc:
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
                importance_value = memory.get("importance")
                if not isinstance(importance_value, (int, float, str)):
                    importance_value = 0.0
                items.append(
                    MemoryItem(
                        content=str(memory["content"]),
                        memory_type=str(
                            memory.get("memoryType") or memory.get("memory_type") or ""
                        ),
                        importance=float(importance_value),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("skipping malformed memory item: %s", exc)
        return items
