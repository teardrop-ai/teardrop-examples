# teardrop-examples

Runnable examples that pay for [Teardrop](https://github.com/teardrop-ai/teardrop) tools and agent runs with [x402](https://x402.org) USDC payments on Base, plus `teardrop-mcp-pay`, a local MCP bridge that lets Claude Desktop, Cursor and Claude Code pay per call under a hard spend cap.

> **These examples spend real money.** They default to Base mainnet: the flagship call costs **$0.002**. There's no public staging deployment, so use a **dedicated wallet funded with about $1 of USDC on Base**. Every signature goes through a guard with low default caps ($0.01 per call, $0.10 per run). Read [SECURITY.md](SECURITY.md) first.

## Pick your path

| You are... | Start with | Command |
|---|---|---|
| Using Claude Desktop, Cursor or Claude Code | [bridge/](bridge/README.md) | `npx -y teardrop-mcp-pay` (via your host config) |
| Building an agent in Python | [python/01_mcp_pay_per_call](python/01_mcp_pay_per_call/__main__.py) | `uv run python -m python.01_mcp_pay_per_call` |
| Building an agent in TypeScript | [typescript/01_mcp_pay_per_call](typescript/01_mcp_pay_per_call/index.ts) | `pnpm --filter teardrop-examples-ts run mcp` |
| Writing a plain HTTP x402 client | [python/02_http_402](python/02_http_402/__main__.py), [typescript/02_fetch_402](typescript/02_fetch_402/index.ts) | `uv run python -m python.02_http_402` |
| Wanting headless prepaid credits | [python/03_machine_bootstrap](python/03_machine_bootstrap/__main__.py) | `MAX_PER_CALL_USDC=50000 uv run python -m python.03_machine_bootstrap` |
| Calling Teardrop from another agent (A2A) | [python/04_a2a_paid_message](python/04_a2a_paid_message/__main__.py) | `uv run python -m python.04_a2a_paid_message [--async]` |
| Paying by card, no crypto | [python/05_credit_quickstart](python/05_credit_quickstart/__main__.py) | `uv run python -m python.05_credit_quickstart` |

## Zero to a paid call

You need [uv](https://docs.astral.sh/uv/) for Python, or Node.js 22.9+ with [pnpm](https://pnpm.io) for TypeScript. Run every command from the repository root.

1. **Clone and configure.**

   ```sh
   git clone https://github.com/teardrop-ai/teardrop-examples.git && cd teardrop-examples
   cp .env.example .env
   ```

2. **Create a payer key.** This writes `~/.teardrop/payer.key` with mode `0600` and prints only the address. Put its path in `.env` as `PAYER_KEY_FILE`.

   ```sh
   uv run python -m python.new_key
   ```

3. **Fund it.** Send about $1 of USDC on Base to that address. No ETH is needed: the facilitator pays gas for EIP-3009 transfers.

4. **Pay for one call.**

   ```sh
   uv run python -m python.01_mcp_pay_per_call          # Python
   pnpm install && pnpm --filter teardrop-examples-ts run mcp   # TypeScript
   ```

   You'll see the ETH price and a Basescan link for the $0.002 settlement.

## The examples

| Example | What it shows | Cost |
|---|---|---|
| `python/01_mcp_pay_per_call` | MCP SDK v2 + `x402MCPSession`: `tools/list`, the `isError` + `structuredContent` challenge, payment in `params._meta["x402/payment"]`, receipt from `_meta["x402/payment-response"]` | $0.002 |
| `typescript/01_mcp_pay_per_call` | The same flow with `createx402MCPClient` from `@x402/mcp` and a viem account | $0.002 |
| `python/02_http_402` | Plain JSON-RPC: HTTP 402 + `PAYMENT-REQUIRED`, retry with `PAYMENT-SIGNATURE`, receipt in `PAYMENT-RESPONSE` | $0.002 |
| `typescript/02_fetch_402` | The same with `wrapFetchWithPaymentFromConfig` from `@x402/fetch` | $0.002 |
| `python/03_machine_bootstrap` | `POST /token {"grant_type":"x402"}` creates a machine org; stores the one-time `client_secret` (mode `0600`); runs `/agent/run` over SSE with `teardrop-sdk` client credentials | $0.05, funds about one run |
| `python/04_a2a_paid_message` | `POST /message:send` paid over the x402 HTTP transport, synchronously or with `Prefer: respond-async` and polling | Global exact price (currently $0.01) |
| `python/05_credit_quickstart` | Email signup, dashboard card top-up, `/agent/run` on credits | Your top-up |

Every example sends `X-Teardrop-Client` with a fixed tag (`ex-py-mcp`, `ex-ts-mcp`, `ex-bridge`, `ex-http`, `ex-bootstrap`, `ex-a2a`) so Teardrop can measure conversions without storing IP addresses or User-Agents. Tags never affect pricing.

## Prices

Per-call prices for tools on `POST /tools/mcp`, in USDC (atomic units in parentheses; 1,000,000 = $1). Regenerate with `uv run python -m python.price_table`.

<!-- price-table:start -->
| Tool | Price per call (atomic) | What it does |
|---|---|---|
| `discover_agents` | free (60/min per IP) | Read-only discovery of opt-in remote A2A agents and public reputation status |
| `get_block` | $0.001000 (1,000) | Get details for an Ethereum or Base block by number, hash, or 'latest' |
| `get_eth_balance` | $0.001000 (1,000) | Get the native ETH balance of an Ethereum or Base address |
| `convert_currency` | $0.002000 (2,000) | Fiat and crypto currency conversion in one call |
| `get_erc20_balance` | $0.002000 (2,000) | Get the ERC-20 token balance of a wallet, including symbol and decimals |
| `get_gas_price` | $0.002000 (2,000) | Current EIP-1559 gas fees on Ethereum or Base: base fee, priority fee, next-block base fee estimate, and network congestion ratio. |
| `get_token_price` | $0.002000 (2,000) | Live crypto prices via CoinGecko with 60s cache, batch up to 50 tokens |
| `get_transaction` | $0.002000 (2,000) | Get details and receipt for an Ethereum or Base transaction by hash |
| `http_fetch` | $0.002000 (2,000) | SSRF-protected URL fetch with clean text extraction |
| `get_chain_metrics` | $0.003000 (3,000) | Blockchain ecosystem health from DeFiLlama — current TVL, 7d/30d TVL trend, and aggregate fees |
| `get_dex_volume` | $0.003000 (3,000) | DEX landscape activity from DeFiLlama — 24h/7d/30d volume, changes, and global volume share |
| `get_lending_rates` | $0.003000 (3,000) | On-chain lending APY snapshot for Aave v3 and Compound v3 by asset and chain |
| `get_protocol_tvl` | $0.003000 (3,000) | DeFi protocol TVL from DeFiLlama — current value, 7d/30d trend, chain breakdown, optional daily history |
| `resolve_ens` | $0.003000 (3,000) | Forward lookup (ENS name → address) or reverse lookup (address → primary ENS name). Returns avatar text record when available. |
| `get_token_approvals` | $0.004000 (4,000) | ERC-20 allowance audit across curated DeFi spenders with unlimited-approval risk flags |
| `get_token_price_historical` | $0.004000 (4,000) | Historical crypto price data via CoinGecko — period stats and daily series for 1–365 day windows |
| `get_wallet_approvals` | $0.004000 (4,000) | DeBank token authorization exposure and protocol risk flags for one chain |
| `get_yield_rates` | $0.004000 (4,000) | DeFi yield pool rates from DeFiLlama — APY, TVL, and token breakdown across 1,000+ protocols and chains |
| `decode_transaction` | $0.005000 (5,000) | Decode transaction calldata into function name and arguments. Returns status (success/revert), gas used, and block number. Uses provided ABI or falls back to 4byte.directory. |
| `get_dex_quote` | $0.005000 (5,000) | Best Uniswap v3 swap quote across all fee tiers on Ethereum and Base, via direct on-chain QuoterV2 calls |
| `get_wallet_portfolio` | $0.005000 (5,000) | Multi-chain wallet balances with live token prices in one call |
| `read_contract` | $0.005000 (5,000) | Call any view/pure function on a smart contract with your ABI fragment. Supports historical queries via block number. State-changing calls are rejected. |
| `get_wallet_history` | $0.006000 (6,000) | DeBank decoded wallet transaction history with protocol, token, exchange, and gas metadata |
| `get_liquidation_risk` | $0.010000 (10,000) | Tiered DeFi liquidation risk across Aave v3 and Compound v3 for up to 50 wallets per call |
| `get_defi_positions` | $0.013000 (13,000) | Aggregate DeFi positions across Aave v3, Compound v3, and Uniswap v3 LP on Ethereum and Base |
| `validate_opportunity` | $0.015000 (15,000) | Composite DeFi yield pool sustainability verdict and risk factor analysis |
| `web_search` | $0.015000 (15,000) | Real-time web search powered by Tavily |
| `get_wallet_positions` | $0.020000 (20,000) | All-chain DeBank protocol positions, token lists, and optional net worth for an EVM wallet |
| `assess_counterparty_risk` | $0.035000 (35,000) | Composite counterparty verdict across approvals, liquidation health, and activity history |
<!-- price-table:end -->

Prices change; the challenge is authoritative and the guard checks it against your caps before signing. Tools priced above $0.01 need a higher `MAX_PER_CALL_USDC`. Marketplace tools listed elsewhere can't be called on `/tools/mcp`.

### Known gaps

- `tools/list` doesn't carry prices yet. The bridge adds them to tool descriptions once Teardrop publishes `_meta["teardrop/price"]`.
- `get_block` and `get_eth_balance` (1,000 atomic) haven't yet been shown to settle through the current facilitators. Use `get_token_price` for a first test.
- `respond-async` A2A tasks and `/token` return no `PAYMENT-RESPONSE` header, so those examples can't print a transaction hash.

## How Teardrop charges

- **Endpoint.** Anonymous x402 is served at `POST https://api.teardrop.dev/tools/mcp`. `initialize` and `tools/list` are free (60 requests per minute per IP); only `tools/call` is paid. `/mcp/v1` accepts JWTs only.
- **Challenge.** Requests with an `mcp-protocol-version` header or `Accept: text/event-stream` get HTTP 200 with `result.isError=true` and the PaymentRequired object in `structuredContent`. Other requests get HTTP 402 with `PAYMENT-REQUIRED`.
- **Paying.** Send `PAYMENT-SIGNATURE` (or legacy `X-PAYMENT`), or put the payload in `params._meta["x402/payment"]`.
- **Terms.** `eip155:8453`, USDC `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`, `exact` scheme (EIP-3009), `maxTimeoutSeconds` 300.
- **Limits.** Each payer can spend at most $5 per 24 hours on anonymous calls (JSON-RPC error `-32029`).
- **Failed settlement.** If the payment doesn't settle, Teardrop withholds the result and returns a new challenge. Nothing is charged, but the guard still counts the signature toward your caps.
- **Free tools.** `calculate`, `get_datetime`, `count_text_stats` and `discover_agents` are free for anonymous callers.

## The bridge

[`teardrop-mcp-pay`](bridge/README.md) is a stdio MCP server that your MCP host launches. It mirrors Teardrop's tools and pays for each `tools/call` through the guard, with a per-call cap, a rolling 24-hour cap kept in a local ledger, and an optional `CONFIRM_ABOVE_USDC` threshold. Host configs are in [bridge/configs](bridge/configs).

## Development

```sh
uv sync && uv run pytest python && uv run ruff check python
pnpm install && pnpm -r typecheck && pnpm -r test
```

The unit tests run every guard refusal and the full MCP and HTTP payment flows against in-process fakes of the gateway, with real EIP-3009 signing and no network. [ci.yml](.github/workflows/ci.yml) runs them on Linux, macOS and Windows.

[prod-canary.yml](.github/workflows/prod-canary.yml) runs the headless examples against production every night under the `ex-canary` tag (the bootstrap runs weekly). It pages `CANARY_ALERT_WEBHOOK` when a step fails or the canary wallet drops below $0.25. Core changes to `mcp_gateway.py`, `onboarding.py` or `a2a_messages.py` should link a green canary run (trigger it with `workflow_dispatch`).

The guard lives here for now. Once the bridge ships, it moves into `teardrop-sdk` and `teardrop-sdk-ts` (and `teardrop pay` in the CLI), and these examples switch to the SDK APIs. The bridge itself stays in this repo until it has 20 weekly active payers, then moves to `x402-mcp-gateway`.

## License

[MIT](LICENSE)
