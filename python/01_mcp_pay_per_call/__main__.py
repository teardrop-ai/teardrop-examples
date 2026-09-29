"""Pay per call over MCP (the Python flagship).

tools/list -> tools/call get_token_price -> isError challenge -> guarded sign -> retry with
params._meta["x402/payment"] -> print the result and the tx hash from _meta["x402/payment-response"].

    uv run python -m python.01_mcp_pay_per_call
"""

from __future__ import annotations

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from x402 import x402Client
from x402.mcp import MCPToolCallResult, x402MCPSession

from .._shared.config import explorer_tx, format_usdc, load_settings
from .._shared.mcp_v2_adapter import McpV2SessionForX402
from .._shared.payer import build_x402_client, load_account, run

TOOL = "get_token_price"
ARGUMENTS = {"tokens": ["ETH"]}


async def call_paid_tool(session: ClientSession, client: x402Client) -> MCPToolCallResult:
    mcp = x402MCPSession(McpV2SessionForX402(session), client)
    await mcp.initialize()
    names = [tool.name for tool in (await mcp.list_tools()).tools]
    print(f"tools/list: {len(names)} tools" + (f", including {TOOL}" if TOOL in names else ""))
    return await mcp.call_tool(TOOL, ARGUMENTS)


def report(result: MCPToolCallResult) -> None:
    for item in result.content:
        if text := getattr(item, "text", None):
            print(text)
    if result.is_error:
        raise RuntimeError(
            "payment did not settle; the result was withheld" if result.payment_made else "tool call failed"
        )
    if not result.payment_made:
        print("no payment was needed for this call")
        return
    receipt = result.payment_response
    if receipt is None or isinstance(receipt, dict) or not receipt.transaction:
        raise RuntimeError(f"paid call returned no usable settlement receipt: {receipt!r}")
    amount = f" {format_usdc(int(receipt.amount))}" if receipt.amount else ""
    print(f"settled{amount}: {explorer_tx(receipt.network, receipt.transaction)}")


async def main() -> None:
    settings = load_settings("ex-py-mcp")
    account = load_account()
    client, _ = build_x402_client(settings, account)
    print(
        f"payer {account.address} on {settings.network}; caps {format_usdc(settings.max_per_call)}/call, "
        f"{format_usdc(settings.max_total)}/session"
    )
    http = httpx2.AsyncClient(headers=settings.headers, timeout=httpx2.Timeout(30, read=300))
    url = f"{settings.base_url}/tools/mcp"
    async with (
        http,
        streamable_http_client(url, http_client=http, terminate_on_close=False) as (read, write),
        ClientSession(read, write) as session,
    ):
        result = await call_paid_tool(session, client)
    report(result)


if __name__ == "__main__":
    run(main)
