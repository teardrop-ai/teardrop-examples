"""End-to-end payment flows against in-process fakes of the Teardrop gateway (no network, real signing)."""

from __future__ import annotations

import base64
import json

import httpx
import pytest
from mcp import ClientSession
from mcp.client._memory import InMemoryTransport
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult, TextContent
from x402 import SettleResponse
from x402.http import decode_payment_signature_header, encode_payment_response_header

from conftest import PAY_TO, TX, accept, challenge, example
from python._shared.config import BASE_MAINNET
from python._shared.payer import GuardRefusal, build_x402_client

pytestmark = pytest.mark.anyio


def fake_gateway(calls: list, price: str = "2000") -> MCPServer:
    """Mimics /tools/mcp for MCP clients: HTTP 200 isError challenge, then a _meta receipt."""
    server = MCPServer("fake-teardrop")

    @server.tool()
    def get_token_price(tokens: list[str], ctx: Context) -> CallToolResult:
        payment = (ctx.request_context.meta or {}).get("x402/payment")
        calls.append(payment)
        if payment is None:
            required = challenge(accept(amount=price))
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(required))],
                structured_content=required,
                is_error=True,
            )
        auth = payment["payload"]["authorization"]
        receipt = {
            "success": True,
            "transaction": TX,
            "network": BASE_MAINNET,
            "payer": auth["from"],
            "amount": auth["value"],
        }
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps({"prices": [{"symbol": t} for t in tokens]}))],
            meta={"x402/payment-response": receipt},
        )

    return server


async def test_mcp_pay_per_call_signs_and_reads_receipt(settings, account, capsys) -> None:
    mcp_example = example("01_mcp_pay_per_call")
    client, guard = build_x402_client(settings, account)
    calls: list = []
    async with InMemoryTransport(fake_gateway(calls)) as (read, write), ClientSession(read, write) as session:
        result = await mcp_example.call_paid_tool(session, client)

    assert result.payment_made and not result.is_error
    assert result.payment_response.transaction == TX
    assert guard.spent == 2000
    assert calls[0] is None
    auth = calls[1]["payload"]["authorization"]
    assert (auth["from"], auth["to"].lower(), auth["value"]) == (account.address, PAY_TO.lower(), "2000")
    mcp_example.report(result)
    assert f"https://basescan.org/tx/{TX}" in capsys.readouterr().out


async def test_mcp_refuses_over_cap_without_retrying(settings, account) -> None:
    mcp_example = example("01_mcp_pay_per_call")
    client, guard = build_x402_client(settings, account)
    calls: list = []
    async with (
        InMemoryTransport(fake_gateway(calls, price="20000")) as (read, write),
        ClientSession(read, write) as session,
    ):
        with pytest.raises(GuardRefusal, match="MAX_PER_CALL_USDC"):
            await mcp_example.call_paid_tool(session, client)
    assert calls == [None]
    assert guard.spent == 0


async def test_http_402_pays_with_payment_signature(settings, account) -> None:
    http_example = example("02_http_402")
    client, guard = build_x402_client(settings, account)
    required = challenge()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert "mcp-protocol-version" not in request.headers
        assert request.headers["accept"] == "application/json"
        signature = request.headers.get("payment-signature")
        if signature is None:
            encoded = base64.b64encode(json.dumps(required).encode()).decode()
            return httpx.Response(402, json=required, headers={"PAYMENT-REQUIRED": encoded})
        payload = decode_payment_signature_header(signature)
        assert payload.accepted.amount == "2000"
        receipt = SettleResponse(success=True, transaction=TX, network=BASE_MAINNET, amount="2000")
        body = {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "{}"}], "isError": False}}
        return httpx.Response(200, json=body, headers={"PAYMENT-RESPONSE": encode_payment_response_header(receipt)})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        data, receipt = await http_example.paid_tool_call(http, "https://api.teardrop.dev/tools/mcp", client)

    assert data["result"]["isError"] is False
    assert receipt is not None and receipt.transaction == TX
    assert len(seen) == 2 and "x-payment" not in seen[1].headers
    assert guard.spent == 2000
