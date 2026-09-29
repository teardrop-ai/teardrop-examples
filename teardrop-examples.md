# Build Order: `teardrop-examples`

- **Status:** Final (critic-reviewed 2026-09-28)
- **Date:** 2026-09-28
- **Evidence:** core `main@2af6dc5` plus the uncommitted working tree (`billing/x402.py`, `teardrop/mcp_gateway.py`, `teardrop/routers/system.py`, `migrations/versions/113_web3_tool_price_floor.sql`), and a live read of `https://api.teardrop.dev/.well-known/x402`. External package versions are as of 2026-09-28.
- **Facilitators (updated after drafting):** the Dexter facilitator has been replaced by `https://facilitator.payai.network` and `https://x402.primer.systems`, both on the `exact` scheme. Dexter-specific claims below are marked as historical.
- **License:** MIT, matching `teardrop-sdk`, `teardrop-sdk-ts` and `teardrop-cli`.
- **Priority:** Revenue funnel first. Developer education second.

## 1. Problem

Production recorded **171 anonymous MCP x402 challenges in 7 days with zero payment headers** and no conversions, although anonymous MCP x402 settlement works on Base mainnet (tx `0x1a0ec7a9…6691`, 2026-09-26). Agents reach the paywall; nothing they run gets through.

Verified causes, most likely first:

1. **MCP hosts can't sign payments.** Claude Desktop, Cursor and Claude Code have no x402 signer. Bridges are stale (`x402-mcp-proxy` 0.0.7) or depend on HTTP 402 (`@civic/x402-mcp`), which never fires because Teardrop sends MCP clients the spec-required HTTP 200 `isError` + `structuredContent` challenge.
2. **Our SDKs and CLI can't pay.** `teardrop-sdk`/`teardrop-sdk-ts` 0.5.0 raise `PaymentRequiredError` ("resolve the payment externally"); `teardrop-cli` 0.3.5 can't sign.
3. **Production challenges are hostile to naive clients.** Deployed code lists `upto` (Permit2) first for zero-cost/unknown tools, breaking `accepts[0]` clients, and the `grant_type=x402` bootstrap offers **upto only**. (Official x402 clients filter to registered schemes, so this alone doesn't explain zero *attempts*.) `get_eth_balance`/`get_block` cost 1000, below the former facilitator Dexter's `exact` floor of 1509 (PayAI/Primer minimums are unverified). The exact-only fixes are committed (`7f1bf67`) but **not deployed**, and the migration 113 price floor was dropped.
4. **Agents can't budget.** No prices in `tools/list` or the server card; only `/marketplace/catalog`, `/marketplace/quote`, `/billing/pricing`.
5. **We can't attribute clients.** Funnel counters exclude IP/User-Agent by design (migration 108); `tool_call_events.source` is a server-set enum (`api|schedule|trigger|a2a`).

Some of the 171 are likely scanners/directory crawlers that will never pay. The goal is to convert the rest and measure the split.

## 2. Goals and non-goals

**Goals**

- **G1:** Zero to a settled paid call in ≤5 minutes, in Python or TypeScript.
- **G2:** MCP host users (Claude Desktop, Cursor, Claude Code) call paid Teardrop tools via a local stdio bridge with a hard spend cap.
- **G3:** Every example works against production, proven nightly in CI — a synthetic monitor for the revenue path.
- **G4:** Conversions from examples are measurable via a bounded client tag.

**Non-goals**

- No new SDK surface: examples use the SDKs where they work and official `x402`/`@x402/*` for signing; proven capabilities are upstreamed later (§9).
- No hosted wallet/custody. No seller flows (see `create-teardrop-agent`).

## 3. Verified ground truth that examples must encode

**MCP x402 endpoint**

- Anonymous x402 is served at `POST https://api.teardrop.dev/tools/mcp` (`teardrop/app.py`, mounted with `MCPGatewayMiddleware`).
- `/mcp/v1` (`teardrop/routers/marketplace_mcp.py`) accepts only a JWT and bills credits. Examples must not point anonymous payers there.
- Only `tools/call` is gated. `initialize` and `tools/list` are public, limited to 60 requests per minute per IP (error −32029).
- **Challenge format** (`_wants_mcp_payment_signal`, `_x402_challenge`): an `mcp-protocol-version` header or `Accept: text/event-stream` gets HTTP 200 with `result.isError=true` and `structuredContent` = PaymentRequired; otherwise HTTP 402 with `PAYMENT-REQUIRED` (v2) and `X-PAYMENT-REQUIRED` (legacy).
- **How to pay:** send `PAYMENT-SIGNATURE`, `X-PAYMENT`, or `params._meta["x402/payment"]`.
- **Receipt:** `result._meta["x402/payment-response"]` for `_meta` payers. After P0-1 deploys, all settled payers also get `PAYMENT-RESPONSE`/`X-PAYMENT-RESPONSE` headers (P1-2).
- **Terms:** `eip155:8453`, USDC `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`, `exact` scheme (EIP-3009), `maxTimeoutSeconds` 300.
- **Facilitators:** `https://facilitator.payai.network` and `https://x402.primer.systems` (pool with failover; settle is pinned to the verifying facilitator).
- **Limits:** per-payer cap of $5 per 24h (`x402_payer_daily_spend_limit_usdc`, returns 429 −32029).
- **Settlement failure:** the result is withheld and a settlement-failed challenge is returned.

**Other monetized entry points**

- **`POST /token {"grant_type":"x402"}`** (`teardrop/routers/auth.py`, `teardrop/onboarding.py`): 402 for `max(run_price, 50,000)`; after payment returns `{access_token, org_id, client_id, client_secret}` (secret shown once). Repeat payments top up the same machine org; human-owned wallets get 409.
- **`POST /message:send`** (`teardrop/routers/a2a_messages.py`): anonymous x402 over the HTTP transport; `Prefer: respond-async` returns 202, then poll `/message:status/{id}`.
- **`/agent/run`:** auth required; new SIWE (machine), `client_credentials` and `email` orgs use credits only; minimum balance `max(run_price, 50,000)`.
- **Credits:** `/register`; Stripe top-up needs a browser; USDC top-up minimum 1,000,000; email registrants can't create machine credentials (`require_credential_recovery`); access tokens last 30 minutes.

**Pricing** (atomic USDC, where 1,000,000 = $1)

- Cheapest useful priced tools, 2,000 each: `get_token_price`, `get_gas_price`, `http_fetch`, `convert_currency`.
- Zero-cost tools (`calculate`, `get_datetime`, `count_text_stats`, `discover_agents`) are free for anonymous callers in `main` (`_ANON_FREE_TOOLS`; limited to 60 per minute per IP). Live v2.0.0 still charges the flat 10,000 until P0-1 deploys. Other zero-cost tools still get the flat exact default.
- **Default demo tool:** `get_token_price` at $0.002.

**Reusable code**

- `scripts/test_x402_payment.py`: lift `_McpV2SessionForX402` (adapts MCP SDK v2 `is_error`/`structured_content`/float timeouts to the v1 names `x402` 2.24.0 expects), `sign_x402_payment` (behind the guard) and the Permit2 allowance check.
- Defects that must not be copied: hard-coded SIWE `chain_id` 84532, onrender URI, fixed arguments, legacy `X-PAYMENT` as the primary header, the `eip155:*` wildcard scheme registration, and unguarded `sign_x402_payment`.

## 4. Backend prerequisites in the core repo (blocking)

Examples that fail against production would damage the funnel, so these ship first.

| ID | Change | Why | Status |
|---|---|---|---|
| **P0-1** | Deploy `main@a0cdf1c` (v2.1.0) **and** set `X402_SCHEME=exact` in the Render environment (dashboard values override `render.yaml` until a Blueprint sync). This ships exact-only MCP requirements (`7f1bf67`), the exact-pinned bootstrap and top-up (`build_usdc_topup_requirements`), server card `x402.scheme=exact`, and an exact-only global list, which `/message:send` uses at the default intro price of 0. | Clients without Permit2 failed on the old `upto`-first and `upto`-only challenges. | **Done.** Live v2.1.0 (read 2026-09-29 01:23 UTC, with cache-busting): `billing.scheme`, `accepts`, `bootstrap.accepts` and server card `x402.scheme` are all `exact`. |
| **P0-2** | Confirm PayAI and Primer settle `exact` via EIP-3009 with one settled Base tx each, checked with `eth_getTransactionReceipt`. One settle must be at 1,000 atomic (`get_eth_balance`, `get_block`); otherwise raise those two tools to 2,000. The migration 113 price floor was dropped, and number 113 is now `a2a_self_serve_allowlist`. Also confirm that production `X402_FACILITATOR_URLS` lists only PayAI and Primer. | Production facilitators are PayAI and Primer only (startup log, 2026-09-28). **PayAI is proven:** tx `0x3a10cb5b…534a` (block 51920266, 21:11:19 UTC, status 1) moved 2,000 atomic to the treasury. The tx sender `0xc669…cB63` is one of the signers PayAI lists, the call went through Multicall3, and USDC emitted `AuthorizationUsed`, which confirms EIP-3009 and a keyless settle. **Primer is unproven:** it has no treasury settlement in the last ~10k blocks. It likely only runs on failover, so a proof run must pin `X402_FACILITATOR_URLS` to Primer. No 1,000-atomic settle has been observed. | Open: Primer settle and a 1,000 settle remain |
| **P1-1** | Bounded client attribution: accept `X-Teardrop-Client` against a closed allowlist (`ex-py-mcp`, `ex-ts-mcp`, `ex-bridge`, `ex-http`, `ex-bootstrap`, `ex-a2a`, `ex-canary`, `other`). Record it in an additive, CHECK-constrained `mcp_call_events.client_tag` column and as tagged surfaces in `VALID_SURFACES` (no primary-key change to `discovery_stage_counts`). Tags are spoofable and never affect pricing. | Measures conversion by client without storing IP or User-Agent. Stays consistent with migration 108. | Open (no code) |
| **P1-2** | Emit `PAYMENT-RESPONSE` for header-paid calls on `/tools/mcp` and `/message:send` | x402 HTTP transport v2 expects it. Clients need the tx hash. | Done in `a0cdf1c` and deployed with v2.1.0 (not yet spot-checked on a live paid call): settled MCP calls (header and `_meta` payers) and synchronous `/message:send` return `PAYMENT-RESPONSE` and `X-PAYMENT-RESPONSE`, and CORS exposes both. `respond-async` (202) and `/token` return no receipt header. |
| **P1-3** | Expose per-tool price in `tools/list` as `_meta["teardrop/price"] = {x402: {amount, asset, network, scheme}, credit_usdc}` (following the existing `_meta["teardrop/reputation"]` convention) and in the server card. Both rails are shown because the rails can diverge: zero-cost tools outside `_ANON_FREE_TOOLS` are 0 on credits but carry the flat exact default over x402. | Lets agents budget before calling | Open (no code) |
| **P2-1** | Change both insufficient-credit messages that point to admin-only `/admin/credits/topup` (`billing/credit.py`, `tools/definitions/delegate_to_agent.py`) to name `/billing/topup/*` | Misleading error sends users to a dead end | Open |
| **P2-2** | Stop listing marketplace tools in the server card when `/tools/mcp` can't run them | `/tools/mcp` registers only platform registry tools (`tools/mcp_server.py`), yet the live card lists the marketplace tool `crypto_price`. Clients call it and fail. | Open, confirmed live |
| **P1-4** | Set `APP_ENV=production` on Render. First clear every `config ⚠` startup warning, because `_validate_production_config` turns those warnings into boot failures. | Live `/health` reports `environment: development` (the dashboard overrides `render.yaml`). As a result, `/agent/run` SSE errors send raw exception text to clients, there's no HSTS header, org-tool webhooks accept `http://`, and production config guards only warn. Examples 03 and 05 expose `/agent/run` errors to external users. | Open, confirmed live |

P0-1 and P0-2 gate the release. P1 items can ship alongside M1 but must land before the metrics in §8 mean anything. Re-verified 2026-09-29 against `main@a0cdf1c` and live `api.teardrop.dev` (v2.1.0).

## 5. Repository layout

```
teardrop-examples/
├── README.md                 # 60-second path per persona; price table; safety box
├── SECURITY.md               # key handling, spend caps, reporting
├── .env.example              # TEARDROP_BASE_URL, PAYER_PRIVATE_KEY, MAX_PER_CALL_USDC, MAX_TOTAL_USDC
├── python/
│   ├── pyproject.toml        # uv; pins x402==2.24.*, mcp>=2,<3, httpx, eth-account
│   ├── _shared/              # payer.py (guarded signer), mcp_v2_adapter.py
│   ├── 01_mcp_pay_per_call/  # anonymous x402 over MCP transport (_meta)
│   ├── 02_http_402/          # plain JSON-RPC over HTTP 402 + PAYMENT-SIGNATURE
│   ├── 03_machine_bootstrap/ # grant_type=x402 → client credential → /agent/run SSE via teardrop-sdk
│   ├── 04_a2a_paid_message/  # /message:send with x402 (sync + respond-async)
│   └── 05_credit_quickstart/ # email register → dashboard top-up (browser) → /agent/run
├── typescript/
│   ├── package.json          # pnpm; @x402/mcp@2.27.x, @x402/fetch@2.27.x, viem
│   ├── 01_mcp_pay_per_call/  # createx402MCPClient against /tools/mcp
│   └── 02_fetch_402/         # wrapFetchWithPaymentFromConfig
├── bridge/                   # teardrop-mcp-pay: stdio MCP server that pays upstream
│   ├── src/                  # TS, built on @x402/mcp client
│   └── configs/              # claude_desktop_config.json, cursor mcp.json, claude code CLI snippet
└── .github/workflows/
    ├── ci.yml                # lint, typecheck, unit (mocked facilitator)
    └── prod-canary.yml       # nightly paid smoke against api.teardrop.dev
```

## 6. Components

### 6.1 Guarded payer (shared across Python and TypeScript)

Every example signs through one guard. There is no raw signing anywhere else. Before signing, the guard checks all of the following and refuses otherwise:

- `network` equals `eip155:8453`, or the configured test network.
- `asset` equals the canonical USDC address for that network.
- `payTo` is in a pinned set. For `api.teardrop.dev`, the set is a list shipped with each release (currently `0xF2Eec9De86274913F85A8aA6427Ad65a9B0bC90a`; config supports several `x402_treasury_addresses`), cross-checked against `accepts[].payTo`. For other hosts, the first-seen set is stored locally, and changes require `TRUSTED_PAY_TO`. Same-server discovery is not a trust anchor on its own, because a compromised server controls both the discovery document and the challenge. **Caps are the primary control.**
- `maxTimeoutSeconds` is at most 300.
- `amount` is at most `MAX_PER_CALL_USDC`, which defaults to 10,000 atomic ($0.01).
- The session total stays at or below `MAX_TOTAL_USDC`, which defaults to 100,000 atomic ($0.10).
- The scheme is `exact`. `upto` is opt-in only and needs `ALLOW_UPTO=1` and an explicit Permit2 allowance step.

The key is read only from an environment variable or file. It is never logged, and errors redact it. Amounts are integer atomic values; floating point is never used.

### 6.2 Python `01_mcp_pay_per_call` (flagship)

- **Flow:** `tools/list` → `tools/call get_token_price {"tokens":["ETH"]}` → receive the challenge → guarded sign → retry with `_meta["x402/payment"]` → print the result and the tx hash from `_meta["x402/payment-response"]`.
- Uses `x402MCPSession` and `_McpV2SessionForX402`, with the adapter lifted and tested.
- Sends `X-Teardrop-Client: ex-py-mcp`.
- **Acceptance:** one command, `uv run python -m python.01_mcp_pay_per_call`, settles on mainnet for $0.002.

### 6.3 TypeScript `01_mcp_pay_per_call`

The same flow using `createx402MCPClient` from `@x402/mcp` 2.27.x (published about 6 days before this spec, so pin the minor version) and a viem account.

### 6.4 `bridge/` — `teardrop-mcp-pay`

This is the component that unblocks MCP hosts.

- **Shape:** stdio MCP server launched by the host (e.g. `npx -y teardrop-mcp-pay`). It connects to `https://api.teardrop.dev/tools/mcp` as a paying `@x402/mcp` client, mirrors upstream `tools/list` (adding prices once P1-3 lands), and runs the guarded payer for each `tools/call`.
- **Spend controls:** per-call cap, daily cap, and an optional `CONFIRM_ABOVE_USDC` threshold that returns a tool error asking the user to raise the cap instead of paying.
- **Configuration:** only the upstream URL and caps are configurable. The payee is pinned as in §6.1.
- **Ledger:** a local append-only JSONL spend log. The daily cap is computed from it, so the cap survives restarts.
- **Distribution:** config snippets for Claude Desktop, Cursor and Claude Code that reference `PAYER_KEY_FILE`. Keys are never inlined, because host configs store `env` values as plaintext JSON.
- **Scope rules:** exact scheme only in v0.1. It stays here until ≥20 weekly active payers (`ex-bridge` tag), then graduates into `x402-mcp-gateway` as the client counterpart. Teardrop-first, but `TEARDROP_BASE_URL` works against any x402-MCP server (meaning you trust that server's payee, within caps).

### 6.5 `03_machine_bootstrap`

**Revenue path B:** a one-time x402 top-up converts an anonymous payer into a credit-rail org.

- **Flow:** `POST /token {"grant_type":"x402"}` → 402 for `max(run_price, 50,000)` → guarded sign, with `MAX_PER_CALL_USDC=50000` set explicitly by the user (the default cap refuses it) → store `client_id` and `client_secret` in a local file with mode 0600 → `teardrop-sdk` `client_credentials` → `/agent/run` SSE → print `USAGE_SUMMARY` and `BILLING_SETTLEMENT`.
- Warns that the secret is shown once, and that one bootstrap funds about one run, because `/agent/run` needs the same 50,000 minimum.
- Refreshes the 30-minute token automatically.

**Dependency:** needs P0-1 (the exact-pinned bootstrap).

### 6.6 `04_a2a_paid_message`

- **Flow:** `POST /message:send` without payment → 402 → sign → retry with `PAYMENT-SIGNATURE` → Task.
- Shows both the synchronous path and the `Prefer: respond-async` path with polling.
- Documents that Teardrop uses the x402 **HTTP** transport here, not the a2a-x402 in-band extension. With `respond-async`, payment is checked after the 202; failures surface as task state `rejected_payment`.

### 6.7 `05_credit_quickstart`

For non-crypto users.

- **Flow:** `/register` (may require a Turnstile captcha) → verify email → top up in the Teardrop dashboard in a browser → `/agent/run`, using 30-minute tokens and `/auth/refresh`.
- A local Stripe page isn't feasible: `return_url` must be HTTPS, and no API exposes the publishable key.
- States plainly that email accounts can't mint machine credentials, and links to example 03 for headless use.
- Excluded from the canary.

## 7. Milestones

| M | Scope | Exit criteria |
|---|---|---|
| **M0** | Core P0-1 and P0-2 deployed | Live `bootstrap.accepts` is exact-only, and the server card shows `x402.scheme=exact`. Unpaid `tools/call get_token_price` and `/message:send` challenges are exact-only, and anonymous `get_datetime` runs free. One EIP-3009 settle per facilitator (PayAI, Primer) is verified via `eth_getTransactionReceipt` at `mainnet.base.org`. The top-level `/.well-known/x402` `accepts` still follows `X402_SCHEME` for `/agent/run` and is out of scope. |
| **M1** | Guarded payer, Python 01, TypeScript 01, HTTP 402 examples; `ci.yml` | Fresh clone to a settled call in under 5 minutes, measured on Windows, macOS and Linux. Unit tests cover every guard refusal. |
| **M2** | `bridge/` v0.1 plus host configs; P1-1 attribution; `prod-canary.yml` (tagged `ex-canary`) | Claude Desktop calls `get_token_price` and it settles. The canary runs nightly and pages on failure. |
| **M3** | Bootstrap, A2A, credit quickstart; P1-2 and P1-3 | All headless examples are green in the canary (bootstrap runs weekly; wallet budget $3/month). The README price table is generated from `/marketplace/catalog`. |
| **M4** | Distribution | Listed in x402 ecosystem docs and Awesome-x402/MCP lists. The bridge is published to npm. A link is added from the Teardrop agent card and server card `documentation` fields. |

## 8. Success metrics

Measured using P1-1 tags; baseline is zero.

- **Primary:** anonymous conversion, measured as `mcp_call_events` rows with `billing_method='x402'`, `settlement_status='settled'` and `client_tag<>'ex-canary'`, divided by `mcp_402_no_payment`. Don't divide by `mcp_402_challenge`, which also counts credit-rail 402s. Also track the absolute count of settled calls per week by client tag.
- **Supporting:**
  - Bridge weekly active payers.
  - Bootstrap conversions: `org_provisioning_events` with `method='x402' AND event_type='settlement' AND settlement_status='settled'`.
  - Canary uptime.
  - Time to first paid call can only be measured client-side, because challenges carry no payer.
- **Kill or rethink trigger:** if 60 days after M2 examples produce fewer than 10 external settled payers, the demand problem is upstream (discovery or product-market fit), not payment mechanics. Redirect effort accordingly.

## 9. Upstreaming

After M2, move the guarded payer into `teardrop-sdk` (`client.pay_with_x402(max_per_call=…)`) and `teardrop-sdk-ts`. Then add `teardrop pay`/`call` to the CLI. The examples then switch to the SDK APIs. Keeping signing logic in the examples permanently would fork the code.

## 10. Risks

| Risk | Mitigation |
|---|---|
| User leaks a mainnet key | Guarded payer, low default caps, dedicated low-balance wallet, keys from env/file only, `.gitignore` covers `.env`/`*.key`, "fund with $1" box in `SECURITY.md`. |
| Malicious server induces payments via the bridge | Pinned `payTo` set, asset/network checks (§6.1), and above all the caps. Docs warn that a third-party base URL means trusting that server. |
| Upstream `@x402/*`/`x402` breaking changes; MCP v1/v2 drift | Pin minor versions; Renovate PRs; canary catches breakage within 24h; keep the adapter until upstream fixes the `isError` read. |
| Canary wallet drains | Hard `MAX_TOTAL_USDC` per run, separate wallet, alert under $0.25. |
| Examples go stale after core changes | Canary runs against production; core PRs touching `mcp_gateway.py`, `onboarding.py` or `a2a_messages.py` link a green canary run. |

## 11. Open questions (product-level)

1. Is there a Base Sepolia staging deployment? If not, examples default to mainnet with $0.002 calls, and the README must say so up front.
2. Who owns the canary budget, and which alert channel should it page?
