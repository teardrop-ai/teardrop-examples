from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType

import pytest
from eth_account import Account
from eth_account.signers.local import LocalAccount

from python._shared.config import BASE_MAINNET, TEARDROP_PAY_TO, USDC, Settings

PAY_TO = TEARDROP_PAY_TO[0]
TX = "0x" + "ab" * 32


def accept(**overrides: object) -> dict:
    return {
        "scheme": "exact",
        "network": BASE_MAINNET,
        "asset": USDC[BASE_MAINNET],
        "amount": "2000",
        "payTo": PAY_TO,
        "maxTimeoutSeconds": 300,
        "extra": {"name": "USD Coin", "version": "2"},
        **overrides,
    }


def challenge(*accepts: dict) -> dict:
    return {
        "x402Version": 2,
        "error": "Payment required",
        "resource": {"url": "https://api.teardrop.dev/tools/mcp", "description": "MCP", "mimeType": "application/json"},
        "accepts": list(accepts) or [accept()],
    }


def example(name: str) -> ModuleType:
    return importlib.import_module(f"python.{name}.__main__")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        base_url="https://api.teardrop.dev",
        network=BASE_MAINNET,
        max_per_call=10_000,
        max_total=100_000,
        allow_upto=False,
        trusted_pay_to=(),
        state_dir=tmp_path,
        client_tag="ex-canary",
    )


@pytest.fixture
def account() -> LocalAccount:
    return Account.create()
