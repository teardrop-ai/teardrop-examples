# Security

These examples sign real USDC payments on Base mainnet. Read this before you fund a wallet.

> **Fund with $1.** Create a new wallet just for these examples and send it about $1 of USDC on Base.
> Never reuse a wallet that holds anything you can't afford to lose.

## Key handling

- Keys are read only from `PAYER_KEY_FILE` (preferred) or `PAYER_PRIVATE_KEY`. Nothing else signs.
- The key is never logged. Error output passes through a redactor that removes the loaded key.
- `.gitignore` covers `.env`, `.env.*`, `*.key`, `*.pem` and `.teardrop/`. Keep the key file outside the repo with mode `0600`:

  ```sh
  mkdir -p ~/.teardrop && chmod 700 ~/.teardrop
  # write the 0x-prefixed key into ~/.teardrop/payer.key with your editor, then:
  chmod 600 ~/.teardrop/payer.key
  ```

- MCP host configs (Claude Desktop, Cursor, Claude Code) store `env` values as plaintext JSON. The bridge configs therefore reference `PAYER_KEY_FILE`; never paste the key itself into a host config.

## The guarded payer

Every example signs through one guard: [python/_shared/payer.py](python/_shared/payer.py) for Python and [bridge/src/guard.ts](bridge/src/guard.ts) for TypeScript and the bridge. Before signing, it refuses unless all of these hold:

| Check | Rule |
|---|---|
| Network | `eip155:8453`, or `eip155:84532` when `TEARDROP_NETWORK` selects it |
| Asset | The canonical USDC address for that network |
| Scheme | `exact` via EIP-3009. `upto` needs `ALLOW_UPTO=1` and a Permit2 approval you send yourself |
| Timeout | `maxTimeoutSeconds` ≤ 300 |
| Per call | `amount` ≤ `MAX_PER_CALL_USDC` (default 10,000 = $0.01) |
| Session | Total signed ≤ `MAX_TOTAL_USDC` (default 100,000 = $0.10) |
| Payee | `payTo` is in the pinned set (below) |

Amounts are integer atomic units; floating point is never used. Every signed authorization counts toward the caps, even if it never settles, because anyone holding it could settle it before it expires.

The bridge adds a rolling 24-hour cap (`MAX_DAILY_USDC`, persisted in `~/.teardrop/bridge-ledger.jsonl` so it survives restarts) and an optional `CONFIRM_ABOVE_USDC` threshold that returns a tool error instead of paying.

## Payee pinning

- **`api.teardrop.dev`:** the payee set ships with each release (`TEARDROP_PAY_TO` in [python/_shared/config.py](python/_shared/config.py) and [bridge/src/trust.ts](bridge/src/trust.ts)). The current treasury is `0xF2Eec9De86274913F85A8aA6427Ad65a9B0bC90a`. Changes to that list must be reviewed against the Teardrop `x402_treasury_addresses` setting.
- **Other hosts:** the first challenge's payees are stored in `~/.teardrop/payto.json` (trust on first use). A later change is refused until you list the new address in `TRUSTED_PAY_TO`.
- Discovery documents are never used as a trust anchor, because a compromised server controls both the discovery document and the challenge.

**Caps are the primary control.** Pointing an example or the bridge at a third-party `TEARDROP_BASE_URL` means trusting that server's payee, up to your caps.

## Reporting a vulnerability

Please don't open a public issue. Use GitHub's private vulnerability reporting on this repository ("Security" tab, "Report a vulnerability"). Include the affected file, a reproduction, and the impact. For vulnerabilities in the Teardrop API itself, follow the policy in the [Teardrop repository](https://github.com/teardrop-ai/teardrop/blob/main/SECURITY.md).
