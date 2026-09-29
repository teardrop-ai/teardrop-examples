"""Adapt an MCP SDK v2 ClientSession to the v1 surface that x402 2.24's x402MCPSession reads.

x402MCPSession reads ``isError``/``structuredContent`` and passes ``timedelta`` timeouts,
while MCP SDK v2 returns ``is_error``/``structured_content`` and expects float seconds.
Delete this adapter once x402 reads the v2 names.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any


class McpV2SessionForX402:
    def __init__(self, session: Any) -> None:
        self._session = session

    async def initialize(self) -> Any:
        return await self._session.initialize()

    async def list_tools(self) -> Any:
        return await self._session.list_tools()

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: timedelta | None = None,
        meta: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        result = await self._session.call_tool(
            name,
            arguments,
            read_timeout_seconds=read_timeout_seconds.total_seconds() if read_timeout_seconds is not None else None,
            meta=meta,
        )
        return SimpleNamespace(
            content=result.content,
            isError=result.is_error,
            structuredContent=result.structured_content,
            meta=result.meta,
        )
