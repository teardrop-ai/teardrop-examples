"""Credit quickstart for non-crypto users: email account, dashboard top-up, then /agent/run.

    uv run python -m python.05_credit_quickstart

Steps: /register (the API may require a Turnstile captcha; if so, sign up in the dashboard) ->
verify your email -> top up in the Teardrop dashboard in a browser (Stripe needs an HTTPS
return URL, so a local page can't do it) -> /agent/run. teardrop-sdk renews the 30-minute
access token for you.

Email accounts can't mint machine credentials. For headless use, see 03_machine_bootstrap.
This example is interactive and is excluded from the canary.
"""

from __future__ import annotations

import os
from getpass import getpass

from teardrop import AsyncTeardropClient
from teardrop.exceptions import ConflictError, ForbiddenError

from .._shared.config import format_usdc, load_settings
from .._shared.payer import run

PROMPT = "What is the current ETH price in USD? Answer in one sentence."
RUN_RESERVE = 50_000
DASHBOARD_URL = os.environ.get("TEARDROP_DASHBOARD_URL", "https://teardrop.dev")


async def register(base_url: str, email: str, password: str) -> bool:
    org_name = input("Organisation name: ").strip()
    async with AsyncTeardropClient(base_url) as anonymous:
        try:
            await anonymous.register(
                org_name=org_name, email=email, password=password, acquisition_source="teardrop-examples"
            )
        except ForbiddenError as exc:
            print(f"Registration through the API was refused ({exc}). Sign up at {DASHBOARD_URL}, then rerun.")
            return False
        except ConflictError:
            print("That email or organisation already exists; continuing with sign-in.")
            return True
    input("Check your inbox, open the verification link, then press Enter... ")
    return True


async def main() -> None:
    settings = load_settings("other")
    email = os.environ.get("TEARDROP_EMAIL") or input("Email: ").strip()
    password = os.environ.get("TEARDROP_PASSWORD") or getpass("Password (8+ characters, at least one digit): ")

    if input("Create a new account? [y/N] ").strip().lower() == "y" and not await register(
        settings.base_url, email, password
    ):
        return

    async with AsyncTeardropClient(settings.base_url, email=email, secret=password) as client:
        balance = (await client.get_balance()).balance_usdc
        while balance < RUN_RESERVE:
            print(
                f"Balance is {format_usdc(balance)}; a run needs at least {format_usdc(RUN_RESERVE)}. "
                f"Top up with a card in the dashboard: {DASHBOARD_URL} (Billing)."
            )
            input("Press Enter after the top-up completes... ")
            balance = (await client.get_balance()).balance_usdc
        print(f"Balance {format_usdc(balance)}. Running the agent:\n")

        async for event in client.run(PROMPT, emit_ui=False):
            if event.type == "TEXT_MESSAGE_CONTENT":
                print(event.data.get("delta", ""), end="", flush=True)
            elif event.type == "BILLING_SETTLEMENT":
                print(f"\n\nCharged {format_usdc(int(event.data.get('cost_usdc', 0)))} in credits.")
            elif event.type == "ERROR":
                print(f"\nerror: {event.data.get('message')}")
    print()


if __name__ == "__main__":
    run(main)
