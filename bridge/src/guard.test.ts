import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";

import { BASE_MAINNET, formatUsdc, GuardRefusal, PaymentGuard, USDC, type Requirement } from "./guard.js";
import { SpendLedger } from "./ledger.js";
import { PayToTrust, TEARDROP_PAY_TO } from "./trust.js";

const PAY_TO = TEARDROP_PAY_TO[0]!;

function requirement(overrides: Partial<Requirement> = {}): Requirement {
  return {
    scheme: "exact",
    network: BASE_MAINNET,
    asset: USDC[BASE_MAINNET]!,
    amount: "2000",
    payTo: PAY_TO,
    maxTimeoutSeconds: 300,
    extra: { name: "USD Coin", version: "2" },
    ...overrides,
  };
}

function guard(overrides: Partial<ConstructorParameters<typeof PaymentGuard>[0]> = {}): PaymentGuard {
  return new PaymentGuard({
    network: BASE_MAINNET,
    maxPerCall: 10_000n,
    maxTotal: 100_000n,
    trust: new PayToTrust({
      baseUrl: "https://api.teardrop.dev",
      trusted: [],
      storePath: join(mkdtempSync(join(tmpdir(), "td-guard-")), "payto.json"),
    }),
    ...overrides,
  });
}

describe("PaymentGuard", () => {
  it("accepts a canonical Teardrop exact requirement", () => {
    assert.equal(guard().refusal(requirement()), undefined);
  });

  const refusals: Array<[string, Partial<Requirement>, RegExp]> = [
    ["wrong network", { network: "eip155:1" }, /network eip155:1/],
    ["wrong asset", { asset: "0x0000000000000000000000000000000000000001" }, /not USDC/],
    ["unknown scheme", { scheme: "stream" }, /scheme stream/],
    ["upto without opt-in", { scheme: "upto" }, /ALLOW_UPTO=1/],
    ["exact via Permit2", { extra: { assetTransferMethod: "permit2" } }, /EIP-3009/],
    ["timeout above 300s", { maxTimeoutSeconds: 301 }, /maxTimeoutSeconds 301/],
    ["fractional amount", { amount: "2000.5" }, /integer atomic/],
    ["negative amount", { amount: "-1" }, /integer atomic/],
    ["amount above per-call cap", { amount: "10001" }, /MAX_PER_CALL_USDC=10000/],
    ["unpinned payee", { payTo: "0x000000000000000000000000000000000000dEaD" }, /not pinned/],
  ];
  for (const [label, overrides, pattern] of refusals) {
    it(`refuses ${label}`, () => {
      assert.match(guard().refusal(requirement(overrides)) ?? "", pattern);
    });
  }

  it("accepts upto only when opted in", () => {
    assert.equal(guard({ allowUpto: true }).refusal(requirement({ scheme: "upto" })), undefined);
  });

  it("refuses above CONFIRM_ABOVE_USDC", () => {
    assert.match(guard({ confirmAbove: 1_000n }).refusal(requirement()) ?? "", /CONFIRM_ABOVE_USDC/);
  });

  it("enforces the session total across selections", () => {
    const g = guard({ maxTotal: 5_000n });
    g.select(2, [requirement()]);
    g.select(2, [requirement()]);
    assert.equal(g.spent, 4_000n);
    assert.throws(() => g.select(2, [requirement()]), (e: unknown) => e instanceof GuardRefusal && /MAX_TOTAL_USDC/.test(e.message));
    assert.equal(g.spent, 4_000n);
  });

  it("enforces an external budget and commits to it", () => {
    const dir = mkdtempSync(join(tmpdir(), "td-ledger-"));
    const ledger = new SpendLedger(join(dir, "ledger.jsonl"), 3_000n);
    const g = guard({ budget: ledger });
    g.select(2, [requirement()]);
    assert.equal(ledger.remaining(), 1_000n);
    assert.match(g.refusal(requirement()) ?? "", /daily cap/);
  });

  it("policy keeps acceptable requirements and drops the rest", () => {
    const upto = requirement({ scheme: "upto", amount: "500000" });
    const exact = requirement();
    assert.deepEqual(guard().policy(2, [upto, exact]), [exact]);
  });

  it("policy throws every reason when nothing is acceptable", () => {
    assert.throws(
      () => guard().policy(2, [requirement({ scheme: "upto" }), requirement({ amount: "50000" })]),
      (e: unknown) => e instanceof GuardRefusal && e.reasons.length === 2,
    );
  });

  it("formats atomic USDC without floating point", () => {
    assert.equal(formatUsdc(2_000n), "$0.002000");
    assert.equal(formatUsdc(1_234_567n), "$1.234567");
  });
});

describe("PayToTrust", () => {
  const store = () => join(mkdtempSync(join(tmpdir(), "td-trust-")), "payto.json");

  it("extends the pinned set with TRUSTED_PAY_TO", () => {
    const extra = "0x1111111111111111111111111111111111111111";
    const trust = new PayToTrust({ baseUrl: "https://api.teardrop.dev", trusted: [extra], storePath: store() });
    assert.equal(trust.refusal(extra, [extra]), undefined);
    assert.equal(trust.refusal(PAY_TO.toLowerCase(), [PAY_TO]), undefined);
  });

  it("trusts other hosts on first use and refuses later changes", () => {
    const path = store();
    const first = "0x2222222222222222222222222222222222222222";
    const trust = new PayToTrust({ baseUrl: "https://example.test", trusted: [], storePath: path });
    assert.equal(trust.refusal(first, [first]), undefined);
    const reloaded = new PayToTrust({ baseUrl: "https://example.test/tools/mcp", trusted: [], storePath: path });
    assert.equal(reloaded.refusal(first, [first]), undefined);
    assert.match(reloaded.refusal(PAY_TO, [PAY_TO]) ?? "", /changed/);
  });
});

describe("SpendLedger", () => {
  it("counts only signed entries from the last 24 hours", () => {
    const path = join(mkdtempSync(join(tmpdir(), "td-ledger-")), "ledger.jsonl");
    let now = Date.parse("2026-09-28T00:00:00Z");
    const ledger = new SpendLedger(path, 10_000n, () => now);
    ledger.commit(requirement(), 2_000n);
    ledger.append({ ts: new Date(now).toISOString(), event: "settled", tool: "t", amount: "2000", tx: "0x1", network: BASE_MAINNET });
    assert.equal(ledger.spentLast24h(), 2_000n);
    now += 24 * 60 * 60 * 1000 + 1;
    assert.equal(ledger.spentLast24h(), 0n);
    assert.equal(ledger.remaining(), 10_000n);
  });
});
