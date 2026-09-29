# teardrop-mcp-pay

A local stdio MCP server that lets Claude Desktop, Cursor and Claude Code call paid [Teardrop](https://github.com/teardrop-ai/teardrop) tools. It connects to `https://api.teardrop.dev/tools/mcp`, mirrors the tool list, and pays each `tools/call` with an x402 USDC authorization on Base. Every signature goes through a guard with hard spend caps.

> **This spends real money.** Use a dedicated wallet with about $1 of USDC on Base. See [SECURITY.md](../SECURITY.md).

## Setup

1. Create a key file outside any repository and fund its address with USDC on Base (no ETH needed). From a clone of this repo, `uv run python -m python.new_key` does this and writes `~/.teardrop/payer.key` with mode `0600`.
2. Add the bridge to your host. Replace the key path with an absolute path. **Never paste the key itself:** host configs store `env` values as plaintext.

| Host | Config file | Snippet |
|---|---|---|
| Claude Desktop | `claude_desktop_config.json` (Settings, Developer, Edit Config) | [configs/claude_desktop_config.json](configs/claude_desktop_config.json) |
| Cursor | `~/.cursor/mcp.json` or `.cursor/mcp.json` | [configs/cursor-mcp.json](configs/cursor-mcp.json) |
| Claude Code | CLI | [configs/claude-code.sh](configs/claude-code.sh) |

On Windows, if the host can't start `npx`, use `"command": "cmd"` with `"args": ["/c", "npx", "-y", "teardrop-mcp-pay"]`.

3. Restart the host and ask something like "What's the ETH price? Use Teardrop's get_token_price." The tool result ends with the amount paid, a Basescan link, and what's left of today's cap.

## Configuration

Only the upstream URL and the caps are configurable. The payee is pinned (see [SECURITY.md](../SECURITY.md)).

| Variable | Default | Meaning |
|---|---|---|
| `PAYER_KEY_FILE` | | Path to a file holding the 0x-prefixed private key (preferred) |
| `PAYER_PRIVATE_KEY` | | The key itself; avoid in host configs |
| `MAX_PER_CALL_USDC` | `10000` ($0.01) | Refuse any single payment above this (atomic USDC) |
| `MAX_DAILY_USDC` | `100000` ($0.10) | Rolling 24-hour cap, computed from the ledger, so it survives restarts |
| `MAX_TOTAL_USDC` | `100000` ($0.10) | Cap for one bridge process |
| `CONFIRM_ABOVE_USDC` | unset | Above this, return a tool error that asks the user to raise the cap instead of paying |
| `TEARDROP_BASE_URL` | `https://api.teardrop.dev` | Any x402 MCP server works; for other hosts you trust that server's payee, within your caps |
| `TRUSTED_PAY_TO` | | Extra payee addresses (comma-separated); needed if a non-Teardrop server's payee changes |
| `TEARDROP_STATE_DIR` | `~/.teardrop` | Holds `bridge-ledger.jsonl` and `payto.json` |

The ledger is an append-only JSONL file. It records every signed authorization (which counts toward the daily cap whether or not it settles) and every settlement with its transaction hash.

## Scope

- `exact` scheme (EIP-3009) only.
- Results are forwarded without `structuredContent`, so the bridge drops each tool's `outputSchema` when mirroring `tools/list`.
- Several host processes can share one ledger, but they don't lock it, so two simultaneous payments can overshoot the daily cap by one call.

## Development

```sh
pnpm install
pnpm --filter teardrop-mcp-pay test    # guard, ledger, and an end-to-end run against a fake Teardrop over in-memory MCP
pnpm --filter teardrop-mcp-pay start   # run from source (reads the variables above)
pnpm --filter teardrop-mcp-pay build   # emits dist/ for npm
```

`teardrop-mcp-pay/payer` exports the guard that the TypeScript examples use.

## License

MIT
