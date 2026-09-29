#!/usr/bin/env sh
# Register teardrop-mcp-pay with Claude Code (user scope). The key stays in a file; only its path is stored.
claude mcp add teardrop --scope user \
  -e PAYER_KEY_FILE="$HOME/.teardrop/payer.key" \
  -e MAX_PER_CALL_USDC=10000 \
  -e MAX_DAILY_USDC=100000 \
  -- npx -y teardrop-mcp-pay
