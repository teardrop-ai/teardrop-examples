"""Pay for one A2A message with x402 over the HTTP transport.

POST /message:send without payment -> 402 -> guarded sign -> retry with PAYMENT-SIGNATURE -> Task.
Teardrop uses the x402 HTTP transport here, not the a2a-x402 in-band extension.

    uv run python -m python.04_a2a_paid_message            # synchronous: Task + PAYMENT-RESPONSE
    uv run python -m python.04_a2a_paid_message --async    # Prefer: respond-async, then poll

With respond-async, payment is verified after the 202. A rejected payment ends the task as
"failed" (internally rejected_payment), and no PAYMENT-RESPONSE header is returned.
"""

from __future__ import annotations

import argparse
import asyncio
import time
import uuid

import httpx
from x402 import parse_payment_required
from x402.http import (
    PAYMENT_REQUIRED_HEADER,
    PAYMENT_RESPONSE_HEADER,
    PAYMENT_SIGNATURE_HEADER,
    decode_payment_required_header,
    decode_payment_response_header,
    encode_payment_signature_header,
)

from .._shared.config import explorer_tx, format_usdc, load_settings
from .._shared.payer import build_x402_client, load_account, run

PROMPT = "In one sentence, what can you help me with?"
TERMINAL_STATES = {"completed", "failed", "canceled", "rejected"}
POLL_SECONDS = 2
POLL_TIMEOUT_SECONDS = 300


def task_text(task: dict) -> str:
    parts = (task.get("status", {}).get("message") or {}).get("parts") or []
    return "\n".join(p.get("text", "") for p in parts if p.get("kind") == "text")


async def send_paid(http: httpx.AsyncClient, client, body: dict, prefer_async: bool) -> httpx.Response:
    challenge = await http.post("/message:send", json=body)
    if challenge.status_code != 402:
        raise RuntimeError(f"expected 402, got {challenge.status_code}: {challenge.text[:300]}")
    header = challenge.headers.get(PAYMENT_REQUIRED_HEADER)
    payment_required = decode_payment_required_header(header) if header else parse_payment_required(challenge.content)
    payload = await client.create_payment_payload(payment_required)
    headers = {PAYMENT_SIGNATURE_HEADER: encode_payment_signature_header(payload)}
    if prefer_async:
        headers["Prefer"] = "respond-async"
    paid = await http.post("/message:send", json=body, headers=headers)
    if paid.status_code == 402:
        raise RuntimeError(f"payment rejected or result withheld: {paid.json().get('error') or paid.text[:300]}")
    paid.raise_for_status()
    return paid


async def poll(http: httpx.AsyncClient, status_path: str) -> dict:
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while True:
        response = await http.get(status_path)
        response.raise_for_status()
        task = response.json()["result"]
        state = task["status"]["state"]
        print(f"  task {task['id']}: {state}")
        if state in TERMINAL_STATES:
            return task
        if time.monotonic() > deadline:
            raise TimeoutError(f"task still {state} after {POLL_TIMEOUT_SECONDS}s; poll {status_path} later")
        await asyncio.sleep(POLL_SECONDS)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--async", dest="prefer_async", action="store_true", help="use Prefer: respond-async")
    args = parser.parse_args()

    settings = load_settings("ex-a2a")
    account = load_account()
    client, guard = build_x402_client(settings, account)
    print(f"payer {account.address}; cap {format_usdc(settings.max_per_call)}/call")

    body = {
        "message": {"role": "user", "parts": [{"kind": "text", "text": PROMPT}]},
        "metadata": {"source": "teardrop-examples"},
        "taskId": f"ex-{uuid.uuid4()}",
    }
    async with httpx.AsyncClient(
        base_url=settings.base_url, headers=settings.headers, timeout=httpx.Timeout(30, read=300)
    ) as http:
        response = await send_paid(http, client, body, args.prefer_async)
        if response.status_code == 202:
            status_path = response.headers.get("Location") or response.json()["result"]["metadata"]["statusPath"]
            print(f"202 Accepted; polling {status_path}")
            task = await poll(http, status_path)
        else:
            task = response.json()["result"]

    print(task_text(task))
    if task["status"]["state"] != "completed":
        raise RuntimeError(f"task ended {task['status']['state']}")
    if args.prefer_async:
        print(f"paid {format_usdc(guard.spent)}; respond-async tasks return no PAYMENT-RESPONSE header")
        return
    receipt_header = response.headers.get(PAYMENT_RESPONSE_HEADER)
    if not receipt_header:
        raise RuntimeError("paid, but the server sent no PAYMENT-RESPONSE header")
    receipt = decode_payment_response_header(receipt_header)
    print(f"settled {format_usdc(guard.spent)}: {explorer_tx(receipt.network, receipt.transaction)}")


if __name__ == "__main__":
    run(main)
