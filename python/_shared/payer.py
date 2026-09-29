"""The guarded payer: every Python example signs through this guard, and nothing signs outside it.

The TypeScript twin lives in bridge/src/guard.ts; keep the two in sync.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import traceback
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any, NoReturn, Protocol, TypeVar
from urllib.parse import urlsplit

import httpx
from eth_account import Account
from eth_account.signers.local import LocalAccount
from x402 import x402Client
from x402.mechanisms.evm.exact import ExactEvmScheme

from .config import (
    MAX_TIMEOUT_SECONDS,
    TEARDROP_HOSTS,
    TEARDROP_PAY_TO,
    USDC,
    Settings,
    format_usdc,
)

PERMIT2_ADDRESS = "0x000000000022D473030F116dDEE9F6B43aC78BA3"
RPC_URLS = {"eip155:8453": "https://mainnet.base.org", "eip155:84532": "https://sepolia.base.org"}
_ATOMIC = re.compile(r"^\d+$")
_HEX_KEY = re.compile(r"^(0x)?([0-9a-fA-F]{64})$")
_SECRETS: set[str] = set()


class Requirement(Protocol):
    scheme: str
    network: str
    asset: str
    amount: str
    pay_to: str
    max_timeout_seconds: int
    extra: dict[str, Any]


R = TypeVar("R", bound=Requirement)


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


class GuardRefusal(Exception):
    def __init__(self, reasons: Sequence[str]) -> None:
        self.reasons = tuple(reasons)
        super().__init__("payment refused by guard: " + "; ".join(self.reasons))


class PayToTrust:
    """Pinned payees for Teardrop's host; trust-on-first-use for any other host.

    Discovery documents are never consulted, because a compromised server controls both
    the discovery document and the challenge. Caps remain the primary control.
    """

    def __init__(self, base_url: str, trusted: Sequence[str], store_path: Path) -> None:
        parts = urlsplit(base_url)
        self.origin = f"{parts.scheme}://{parts.netloc}"
        self.store_path = store_path
        pinned = TEARDROP_PAY_TO if parts.hostname in TEARDROP_HOSTS else ()
        combined = {a.lower() for a in (*pinned, *trusted)}
        self._pinned = combined or None

    def refusal(self, pay_to: str, offered: Sequence[str]) -> str | None:
        candidate = pay_to.lower()
        if self._pinned is not None:
            if candidate in self._pinned:
                return None
            return (
                f"payTo {pay_to} is not pinned for {self.origin}; if the payee legitimately changed, set TRUSTED_PAY_TO"
            )
        store = json.loads(self.store_path.read_text(encoding="utf-8")) if self.store_path.is_file() else {}
        known = store.get(self.origin)
        if known is None:
            known = sorted({a.lower() for a in offered})
            store[self.origin] = known
            self.store_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.store_path.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")
            os.chmod(self.store_path, 0o600)
            log(f"trusting payTo {', '.join(known)} for {self.origin} on first use (stored in {self.store_path})")
        if candidate in known:
            return None
        return f"payTo for {self.origin} changed from {', '.join(known)} to {pay_to}; set TRUSTED_PAY_TO to accept it"


class PaymentGuard:
    def __init__(
        self,
        *,
        network: str,
        trust: PayToTrust,
        max_per_call: int,
        max_total: int,
        allow_upto: bool = False,
        on_commit: Callable[[Requirement, int], None] | None = None,
    ) -> None:
        self.network = network
        self.trust = trust
        self.max_per_call = max_per_call
        self.max_total = max_total
        self.allow_upto = allow_upto
        self.on_commit = on_commit
        self.spent = 0

    def refusal(self, req: Requirement, offered: Sequence[str] | None = None) -> str | None:
        """Return why ``req`` must not be signed, or None if it may be."""
        if req.network != self.network:
            return f"network {req.network} is not the configured network {self.network}"
        usdc = USDC.get(self.network)
        if usdc is None or req.asset.lower() != usdc.lower():
            return f"asset {req.asset} is not USDC on {self.network}"
        if req.scheme == "upto":
            if not self.allow_upto:
                return "scheme upto is opt-in; set ALLOW_UPTO=1 after approving Permit2"
        elif req.scheme != "exact":
            return f"scheme {req.scheme} is not supported"
        else:
            method = (req.extra or {}).get("assetTransferMethod")
            if method not in (None, "eip3009"):
                return f"exact via {method} is not supported; only EIP-3009 authorizations are signed"
        if req.max_timeout_seconds > MAX_TIMEOUT_SECONDS:
            return f"maxTimeoutSeconds {req.max_timeout_seconds} exceeds {MAX_TIMEOUT_SECONDS}"
        if not _ATOMIC.fullmatch(str(req.amount)):
            return f"amount {req.amount!r} is not an integer atomic value"
        amount = int(req.amount)
        if amount > self.max_per_call:
            return (
                f"amount {format_usdc(amount)} exceeds MAX_PER_CALL_USDC={self.max_per_call} "
                f"({format_usdc(self.max_per_call)})"
            )
        if self.spent + amount > self.max_total:
            return (
                f"session total would reach {format_usdc(self.spent + amount)}, above MAX_TOTAL_USDC={self.max_total}"
            )
        return self.trust.refusal(req.pay_to, offered if offered is not None else [req.pay_to])

    def policy(self, _x402_version: int, requirements: list[R]) -> list[R]:
        """x402 PaymentPolicy: keep acceptable requirements, or raise with every reason if none are."""
        offered = list(dict.fromkeys(r.pay_to for r in requirements))
        accepted: list[R] = []
        reasons: list[str] = []
        for req in requirements:
            reason = self.refusal(req, offered)
            if reason is None:
                accepted.append(req)
            else:
                reasons.append(reason)
        if not accepted:
            raise GuardRefusal(list(dict.fromkeys(reasons)))
        # With ALLOW_UPTO=1 both schemes may pass; exact never needs a Permit2 allowance, so it goes first.
        return sorted(accepted, key=lambda r: r.scheme != "exact")

    def select(self, _x402_version: int, requirements: list[R]) -> R:
        """x402 requirements selector: re-check the first acceptable requirement and commit its amount."""
        if not requirements:
            raise GuardRefusal(["no payment requirements offered"])
        chosen = requirements[0]
        reason = self.refusal(chosen)
        if reason is not None:
            raise GuardRefusal([reason])
        amount = int(chosen.amount)
        self.spent += amount
        if self.on_commit is not None:
            self.on_commit(chosen, amount)
        return chosen


def redact(text: str) -> str:
    """Remove the loaded private key from text before it is printed."""
    for secret in _SECRETS:
        text = re.sub(rf"(0x)?{secret}", "[redacted]", text, flags=re.IGNORECASE)
    return text


def load_account() -> LocalAccount:
    """Read the payer key from PAYER_PRIVATE_KEY or PAYER_KEY_FILE. The key is never logged."""
    raw = os.environ.get("PAYER_PRIVATE_KEY", "").strip()
    key_file = os.environ.get("PAYER_KEY_FILE", "").strip()
    if not raw and key_file:
        raw = Path(key_file).expanduser().read_text(encoding="utf-8").strip()
    if not raw:
        raise ValueError("set PAYER_KEY_FILE (preferred) or PAYER_PRIVATE_KEY; see SECURITY.md")
    match = _HEX_KEY.fullmatch(raw)
    if match is None:
        raise ValueError("payer key must be 32 bytes of hex (optionally 0x-prefixed)")
    _SECRETS.add(match.group(2).lower())
    return Account.from_key("0x" + match.group(2))


def permit2_allowance(settings: Settings, owner: str) -> int:
    """Read the owner's USDC allowance for Permit2 with a raw eth_call (upto only)."""
    data = "0xdd62ed3e" + owner[2:].lower().rjust(64, "0") + PERMIT2_ADDRESS[2:].lower().rjust(64, "0")
    rpc = os.environ.get("BASE_RPC_URL", "").strip() or RPC_URLS[settings.network]
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": USDC[settings.network], "data": data}, "latest"],
    }
    response = httpx.post(rpc, json=body, timeout=15)
    response.raise_for_status()
    return int(response.json()["result"], 16)


def build_x402_client(settings: Settings, account: LocalAccount) -> tuple[x402Client, PaymentGuard]:
    guard = PaymentGuard(
        network=settings.network,
        trust=PayToTrust(settings.base_url, settings.trusted_pay_to, settings.state_dir / "payto.json"),
        max_per_call=settings.max_per_call,
        max_total=settings.max_total,
        allow_upto=settings.allow_upto,
        on_commit=lambda r, amount: log(
            f"signing {format_usdc(amount)} USDC ({r.scheme}) to {r.pay_to} on {r.network}"
        ),
    )
    client = x402Client(payment_requirements_selector=guard.select)
    client.register(settings.network, ExactEvmScheme(signer=account))
    if settings.allow_upto:
        if permit2_allowance(settings, account.address) == 0:
            raise ValueError(
                f"ALLOW_UPTO=1 needs a one-time USDC approval for Permit2 ({PERMIT2_ADDRESS}) from "
                f"{account.address}; send it from your wallet first, these examples never do"
            )
        from x402.mechanisms.evm.upto import UptoEvmScheme

        client.register(settings.network, UptoEvmScheme(signer=account))
    client.register_policy(guard.policy)
    return client, guard


def _leaf(exc: BaseException) -> BaseException:
    # anyio task groups wrap errors; surface the single underlying cause.
    while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
        exc = exc.exceptions[0]
    return exc


def run(main: Callable[[], Awaitable[None]]) -> NoReturn:
    """Run an example, printing redacted errors and exiting non-zero on failure."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except BaseException as exc:  # noqa: BLE001 - top-level reporter for example scripts
        cause = _leaf(exc)
        if isinstance(cause, SystemExit):
            raise cause from None
        if os.environ.get("DEBUG") == "1":
            log(redact("".join(traceback.format_exception(exc))))
        if isinstance(cause, GuardRefusal):
            log("refused: " + "; ".join(cause.reasons))
            sys.exit(2)
        log(redact(f"error: {type(cause).__name__}: {cause}"))
        sys.exit(1)
    sys.exit(0)
