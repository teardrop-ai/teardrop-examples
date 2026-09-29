"""Revenue path B: one x402 payment turns an anonymous wallet into a credit-funded machine org.

POST /token {"grant_type":"x402"} -> 402 for max(run_price, 50,000) atomic -> guarded sign ->
store client_id/client_secret (mode 0600) -> teardrop-sdk client_credentials -> /agent/run SSE.

The bootstrap costs $0.05, above the default $0.01 per-call cap, so opt in explicitly:

    MAX_PER_CALL_USDC=50000 uv run python -m python.03_machine_bootstrap
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
from teardrop import AsyncTeardropClient
from teardrop.exceptions import PaymentRequiredError
from x402 import parse_payment_required
from x402.http import (
    PAYMENT_REQUIRED_HEADER,
    PAYMENT_SIGNATURE_HEADER,
    decode_payment_required_header,
    encode_payment_signature_header,
)

from .._shared.config import format_usdc, load_settings
from .._shared.payer import GuardRefusal, build_x402_client, load_account, log, run

PROMPT = "What is the current ETH price in USD? Answer in one sentence."
RUN_RESERVE = 50_000


def save_credentials(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.chmod(path, 0o600)


async def bootstrap(settings, client) -> dict:
    async with httpx.AsyncClient(base_url=settings.base_url, headers=settings.headers, timeout=60) as http:
        challenge = await http.post("/token", json={"grant_type": "x402"})
        if challenge.status_code == 404:
            raise RuntimeError("x402 onboarding is not enabled on this deployment")
        if challenge.status_code != 402:
            raise RuntimeError(f"expected 402 from /token, got {challenge.status_code}: {challenge.text[:300]}")
        header = challenge.headers.get(PAYMENT_REQUIRED_HEADER)
        payment_required = (
            decode_payment_required_header(header) if header else parse_payment_required(challenge.content)
        )
        try:
            payload = await client.create_payment_payload(payment_required)
        except GuardRefusal:
            prices = sorted({int(a.amount) for a in payment_required.accepts})
            log(f"bootstrap costs {', '.join(format_usdc(p) for p in prices)}; raise MAX_PER_CALL_USDC to allow it")
            raise

        paid = await http.post(
            "/token",
            json={"grant_type": "x402"},
            headers={PAYMENT_SIGNATURE_HEADER: encode_payment_signature_header(payload)},
        )
    if paid.status_code == 409:
        raise RuntimeError("this wallet already belongs to a human-owned org; sign in with SIWE instead")
    if paid.status_code == 402:
        raise RuntimeError(f"payment rejected: {paid.json().get('error') or paid.text[:300]}")
    paid.raise_for_status()
    return paid.json()


async def main() -> None:
    settings = load_settings("ex-bootstrap")
    account = load_account()
    client, guard = build_x402_client(settings, account)
    creds_path = settings.state_dir / f"bootstrap-{account.address.lower()}.json"
    print(f"payer {account.address}; bootstrapping a machine org on {settings.base_url}")
    print("note: one bootstrap funds about one /agent/run, which needs the same 50,000-atomic ($0.05) reserve")

    data = await bootstrap(settings, client)
    print(f"org {data['org_id']} funded with {format_usdc(guard.spent)}; client_id {data['client_id']}")

    if data.get("client_secret"):
        save_credentials(
            creds_path,
            {
                "base_url": settings.base_url,
                "org_id": data["org_id"],
                "client_id": data["client_id"],
                "client_secret": data["client_secret"],
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
        print(f"client_secret is shown only once; saved to {creds_path} (mode 0600)")
    elif creds_path.is_file():
        print(f"top-up of an existing org; reusing credentials from {creds_path}")
    else:
        print(
            "top-up of an existing org, but no saved secret was found; using the 30-minute access token. "
            "Recover a secret with SIWE and POST /org/credentials/regenerate."
        )

    if creds_path.is_file():
        saved = json.loads(creds_path.read_text(encoding="utf-8"))
        agent = AsyncTeardropClient(
            settings.base_url, client_id=saved["client_id"], client_secret=saved["client_secret"]
        )
    else:
        agent = AsyncTeardropClient(settings.base_url, token=data["access_token"])

    usage = billing = None
    async with agent:
        try:
            async for event in agent.run(PROMPT, emit_ui=False):
                if event.type == "TEXT_MESSAGE_CONTENT":
                    print(event.data.get("delta", ""), end="", flush=True)
                elif event.type == "USAGE_SUMMARY":
                    usage = event.data
                elif event.type == "BILLING_SETTLEMENT":
                    billing = event.data
                elif event.type == "ERROR":
                    log(f"run error: {event.data}")
        except PaymentRequiredError:
            balance = await agent.get_balance()
            raise RuntimeError(
                f"balance {format_usdc(balance.balance_usdc)} is below the {format_usdc(RUN_RESERVE)} run reserve; "
                "run this example again or top up via /billing/topup/usdc (minimum $1)"
            ) from None
    print()
    print(f"USAGE_SUMMARY {json.dumps(usage)}")
    print(f"BILLING_SETTLEMENT {json.dumps(billing)}")


if __name__ == "__main__":
    run(main)
