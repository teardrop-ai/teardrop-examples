"""Settings shared by every Python example, read from the environment and an optional .env file."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASE_URL = "https://api.teardrop.dev"
BASE_MAINNET = "eip155:8453"
BASE_SEPOLIA = "eip155:84532"
USDC = {
    BASE_MAINNET: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    BASE_SEPOLIA: "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
}
MAX_TIMEOUT_SECONDS = 300

# Payees shipped with each release for Teardrop's production API. Review SECURITY.md before editing.
TEARDROP_PAY_TO = ("0xF2Eec9De86274913F85A8aA6427Ad65a9B0bC90a",)
TEARDROP_HOSTS = frozenset({"api.teardrop.dev"})

# Closed allowlist for X-Teardrop-Client. Tags are spoofable and never affect pricing.
CLIENT_TAGS = frozenset(
    {"ex-py-mcp", "ex-ts-mcp", "ex-bridge", "ex-http", "ex-bootstrap", "ex-a2a", "ex-canary", "other"}
)

REPO_ROOT = Path(__file__).resolve().parents[2]
_ATOMIC = re.compile(r"^\d+$")


def load_dotenv(path: Path = REPO_ROOT / ".env") -> None:
    """Load KEY=VALUE lines without overriding variables that are already set."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def atomic_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    if not _ATOMIC.fullmatch(raw):
        raise ValueError(f"{name} must be an integer number of atomic USDC units (1000000 = $1), got {raw!r}")
    return int(raw)


def format_usdc(atomic: int) -> str:
    sign = "-" if atomic < 0 else ""
    atomic = abs(atomic)
    return f"{sign}${atomic // 1_000_000}.{atomic % 1_000_000:06d}"


def explorer_tx(network: str, tx: str) -> str:
    host = "sepolia.basescan.org" if network == BASE_SEPOLIA else "basescan.org"
    return f"https://{host}/tx/{tx}"


@dataclass(frozen=True)
class Settings:
    base_url: str
    network: str
    max_per_call: int
    max_total: int
    allow_upto: bool
    trusted_pay_to: tuple[str, ...]
    state_dir: Path
    client_tag: str

    @property
    def headers(self) -> dict[str, str]:
        return {"X-Teardrop-Client": self.client_tag}


def load_settings(default_tag: str) -> Settings:
    load_dotenv()
    network = os.environ.get("TEARDROP_NETWORK", "").strip() or BASE_MAINNET
    if network not in USDC:
        raise ValueError(f"TEARDROP_NETWORK must be {BASE_MAINNET} or {BASE_SEPOLIA}, got {network!r}")
    tag = os.environ.get("TEARDROP_CLIENT_TAG", "").strip() or default_tag
    state_dir = os.environ.get("TEARDROP_STATE_DIR", "").strip()
    return Settings(
        base_url=(os.environ.get("TEARDROP_BASE_URL", "").strip() or DEFAULT_BASE_URL).rstrip("/"),
        network=network,
        max_per_call=atomic_env("MAX_PER_CALL_USDC", 10_000),
        max_total=atomic_env("MAX_TOTAL_USDC", 100_000),
        allow_upto=os.environ.get("ALLOW_UPTO") == "1",
        trusted_pay_to=tuple(a.strip() for a in os.environ.get("TRUSTED_PAY_TO", "").split(",") if a.strip()),
        state_dir=Path(state_dir) if state_dir else Path.home() / ".teardrop",
        client_tag=tag if tag in CLIENT_TAGS else "other",
    )
