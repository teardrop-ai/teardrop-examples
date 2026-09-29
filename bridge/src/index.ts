#!/usr/bin/env node
import { createRequire } from "node:module";
import { join } from "node:path";

import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { ExactEvmScheme } from "@x402/evm/exact/client";
import { createx402MCPClient } from "@x402/mcp";

import { SpendLedger } from "./ledger.js";
import { atomicEnv, createGuard, formatUsdc, loadAccount, loadSettings, redact } from "./payer.js";
import { createBridgeServer } from "./server.js";

const { name, version } = createRequire(import.meta.url)("../package.json") as { name: string; version: string };

// stdout carries the MCP protocol, so every log line goes to stderr.
const log = (message: string): void => console.error(`[${name}] ${redact(message)}`);

async function main(): Promise<void> {
  const settings = loadSettings("ex-bridge");
  const account = loadAccount();
  const dailyCap = atomicEnv(process.env, "MAX_DAILY_USDC", 100_000n);
  const confirmAbove = process.env.CONFIRM_ABOVE_USDC ? atomicEnv(process.env, "CONFIRM_ABOVE_USDC", 0n) : undefined;
  const ledger = new SpendLedger(join(settings.stateDir, "bridge-ledger.jsonl"), dailyCap);
  const guard = createGuard(settings, { budget: ledger, confirmAbove, log });

  const upstream = createx402MCPClient({
    name,
    version,
    schemes: [{ network: settings.network, client: new ExactEvmScheme(account) }],
    policies: [guard.policy],
    paymentRequirementsSelector: guard.select,
    autoPayment: true,
  });
  const url = new URL(`${settings.baseUrl}/tools/mcp`);
  await upstream.connect(
    new StreamableHTTPClientTransport(url, { requestInit: { headers: { "X-Teardrop-Client": settings.clientTag } } }),
  );

  const server = createBridgeServer(upstream, ledger, { name, version }, log);
  await server.connect(new StdioServerTransport());
  log(
    `payer ${account.address} -> ${url.href} on ${settings.network}; caps ${formatUsdc(settings.maxPerCall)}/call, ` +
      `${formatUsdc(dailyCap)}/24h (${formatUsdc(ledger.remaining())} left), ledger ${ledger.path}`,
  );
}

main().catch((error: unknown) => {
  log(`fatal: ${error instanceof Error ? error.message : String(error)}`);
  process.exit(1);
});
