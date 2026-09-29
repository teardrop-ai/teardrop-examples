"""Plain JSON-RPC over the x402 HTTP transport.

Without MCP headers, the gateway answers an unpaid tools/call with HTTP 402 and a
PAYMENT-REQUIRED header. We sign through the guard, retry with PAYMENT-SIGNATURE, and
read the receipt from PAYMENT-RESPONSE.

    uv run python -m python.02_http_402
"""

from __future__ import annotations

import httpx
from x402 import SettleResponse, parse_payment_required, x402Client
from x402.http import (
    PAYMENT_REQUIRED_HEADER,
    PAYMENT_RESPONSE_HEADER,
    PAYMENT_SIGNATURE_HEADER,
    X_PAYMENT_RESPONSE_HEADER,
    decode_payment_required_header,
    decode_payment_response_header,
    encode_payment_signature_header,
)

from .._shared.config import explorer_tx, format_usdc, load_settings
from .._shared.payer import build_x402_client, load_account, run

TOOL = "get_token_price"
ARGUMENTS = {"tokens": ["ETH"]}
# Accepting only JSON (no text/event-stream, no mcp-protocol-version) selects the HTTP 402 challenge.
HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}


async def paid_tool_call(http: httpx.AsyncClient, url: str, client: x402Client) -> tuple[dict, SettleResponse | None]:
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": TOOL, "arguments": ARGUMENTS}}
    response = await http.post(url, json=body, headers=HEADERS)
    if response.status_code != 402:
        response.raise_for_status()
        return response.json(), None

    header = response.headers.get(PAYMENT_REQUIRED_HEADER)
    payment_required = decode_payment_required_header(header) if header else parse_payment_required(response.content)
    payload = await client.create_payment_payload(payment_required)

    paid = await http.post(
        url, json=body, headers={**HEADERS, PAYMENT_SIGNATURE_HEADER: encode_payment_signature_header(payload)}
    )
    if paid.status_code == 402:
        raise RuntimeError(f"payment rejected: {paid.json().get('error') or paid.text[:300]}")
    paid.raise_for_status()
    receipt = paid.headers.get(PAYMENT_RESPONSE_HEADER) or paid.headers.get(X_PAYMENT_RESPONSE_HEADER)
    if receipt is None:
        raise RuntimeError("paid, but the server sent no PAYMENT-RESPONSE header")
    return paid.json(), decode_payment_response_header(receipt)


async def main() -> None:
    settings = load_settings("ex-http")
    account = load_account()
    client, _ = build_x402_client(settings, account)
    print(f"payer {account.address} on {settings.network}; cap {format_usdc(settings.max_per_call)}/call")

    async with httpx.AsyncClient(headers=settings.headers, timeout=httpx.Timeout(30, read=300)) as http:
        data, receipt = await paid_tool_call(http, f"{settings.base_url}/tools/mcp", client)

    result = data.get("result") or {}
    if "error" in data or result.get("isError"):
        raise RuntimeError(f"tool call failed: {data.get('error') or result}")
    for item in result.get("content", []):
        if item.get("type") == "text":
            print(item["text"])
    if receipt is None:
        print("no payment was needed for this call")
        return
    amount = f" {format_usdc(int(receipt.amount))}" if receipt.amount else ""
    print(f"settled{amount}: {explorer_tx(receipt.network, receipt.transaction)}")


if __name__ == "__main__":
    run(main)
