from __future__ import annotations

from pathlib import Path

import pytest
from x402.schemas import PaymentRequirements

from conftest import PAY_TO, accept
from python._shared import payer
from python._shared.config import atomic_env, format_usdc
from python._shared.payer import GuardRefusal, PaymentGuard, PayToTrust


def req(**overrides: object) -> PaymentRequirements:
    return PaymentRequirements.model_validate(accept(**overrides))


def guard(tmp_path: Path, **overrides: object) -> PaymentGuard:
    options: dict = {
        "network": "eip155:8453",
        "trust": PayToTrust("https://api.teardrop.dev", (), tmp_path / "payto.json"),
        "max_per_call": 10_000,
        "max_total": 100_000,
    }
    options.update(overrides)
    return PaymentGuard(**options)


def test_accepts_canonical_teardrop_requirement(tmp_path: Path) -> None:
    assert guard(tmp_path).refusal(req()) is None


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"network": "eip155:1"}, "network eip155:1"),
        ({"asset": "0x0000000000000000000000000000000000000001"}, "not USDC"),
        ({"scheme": "stream"}, "scheme stream"),
        ({"scheme": "upto"}, "ALLOW_UPTO=1"),
        ({"extra": {"assetTransferMethod": "permit2"}}, "EIP-3009"),
        ({"maxTimeoutSeconds": 301}, "maxTimeoutSeconds 301"),
        ({"amount": "2000.5"}, "integer atomic"),
        ({"amount": "-1"}, "integer atomic"),
        ({"amount": "10001"}, "MAX_PER_CALL_USDC=10000"),
        ({"payTo": "0x000000000000000000000000000000000000dEaD"}, "not pinned"),
    ],
)
def test_refusals(tmp_path: Path, overrides: dict, expected: str) -> None:
    reason = guard(tmp_path).refusal(req(**overrides))
    assert reason is not None and expected in reason


def test_upto_only_when_opted_in(tmp_path: Path) -> None:
    assert guard(tmp_path, allow_upto=True).refusal(req(scheme="upto")) is None


def test_session_total_is_enforced_across_selections(tmp_path: Path) -> None:
    g = guard(tmp_path, max_total=5_000)
    g.select(2, [req()])
    g.select(2, [req()])
    with pytest.raises(GuardRefusal, match="MAX_TOTAL_USDC"):
        g.select(2, [req()])
    assert g.spent == 4_000


def test_policy_filters_and_prefers_exact(tmp_path: Path) -> None:
    upto, exact = req(scheme="upto", amount="5000"), req()
    assert guard(tmp_path).policy(2, [upto, exact]) == [exact]
    assert guard(tmp_path, allow_upto=True).policy(2, [upto, exact]) == [exact, upto]


def test_policy_raises_every_reason_when_nothing_is_acceptable(tmp_path: Path) -> None:
    with pytest.raises(GuardRefusal) as info:
        guard(tmp_path).policy(2, [req(scheme="upto"), req(amount="50000")])
    assert len(info.value.reasons) == 2


def test_trusted_pay_to_extends_pinned_set(tmp_path: Path) -> None:
    extra = "0x1111111111111111111111111111111111111111"
    trust = PayToTrust("https://api.teardrop.dev", (extra,), tmp_path / "payto.json")
    assert trust.refusal(extra, [extra]) is None
    assert trust.refusal(PAY_TO.lower(), [PAY_TO]) is None


def test_other_hosts_are_trusted_on_first_use_then_pinned(tmp_path: Path) -> None:
    store = tmp_path / "payto.json"
    first = "0x2222222222222222222222222222222222222222"
    assert PayToTrust("https://example.test", (), store).refusal(first, [first]) is None
    later = PayToTrust("https://example.test/tools/mcp", (), store)
    assert later.refusal(first, [first]) is None
    assert "changed" in (later.refusal(PAY_TO, [PAY_TO]) or "")


def test_load_account_validates_and_redacts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    key = "11" * 32
    monkeypatch.delenv("PAYER_PRIVATE_KEY", raising=False)
    key_file = tmp_path / "payer.key"
    key_file.write_text(f"0x{key}\n", encoding="utf-8")
    monkeypatch.setenv("PAYER_KEY_FILE", str(key_file))
    account = payer.load_account()
    assert account.address.startswith("0x")
    assert payer.redact(f"boom 0x{key.upper()} boom") == "boom [redacted] boom"

    monkeypatch.setenv("PAYER_PRIVATE_KEY", "not-a-key")
    with pytest.raises(ValueError, match="32 bytes of hex") as info:
        payer.load_account()
    assert "not-a-key" not in str(info.value)


def test_atomic_env_rejects_decimals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_PER_CALL_USDC", "0.01")
    with pytest.raises(ValueError, match="atomic"):
        atomic_env("MAX_PER_CALL_USDC", 10_000)


def test_format_usdc_uses_integer_math() -> None:
    assert format_usdc(2_000) == "$0.002000"
    assert format_usdc(1_234_567) == "$1.234567"
