import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, describe, it } from "node:test";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { CallToolRequestSchema, ListToolsRequestSchema, type CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import { ExactEvmScheme } from "@x402/evm/exact/client";
import { createx402MCPClient } from "@x402/mcp";
import { generatePrivateKey, privateKeyToAccount } from "viem/accounts";

import { BASE_MAINNET, USDC } from "./guard.js";
import { SpendLedger } from "./ledger.js";
import { createGuard, loadSettings } from "./payer.js";
import { createBridgeServer } from "./server.js";
import { TEARDROP_PAY_TO } from "./trust.js";

const TX = `0x${"ab".repeat(32)}`;
const PRICES: Record<string, string> = { get_token_price: "2000", get_wallet_positions: "20000" };

/** Mimics the /tools/mcp gateway: an isError + structuredContent challenge, then a `_meta` receipt. */
function fakeTeardrop(calls: Array<{ name: string; paid: boolean }>): Server {
  const server = new Server({ name: "fake-teardrop", version: "0.0.0" }, { capabilities: { tools: {} } });
  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: Object.entries(PRICES).map(([name, amount]) => ({
      name,
      inputSchema: { type: "object" as const },
      outputSchema: { type: "object" as const },
      _meta: { "teardrop/price": { x402: { amount } } },
    })),
  }));
  server.setRequestHandler(CallToolRequestSchema, async (request): Promise<CallToolResult> => {
    const name = request.params.name;
    const payment = request.params._meta?.["x402/payment"] as
      | { accepted: { amount: string }; payload: { authorization: { from: string; to: string; value: string } } }
      | undefined;
    calls.push({ name, paid: payment !== undefined });
    const paymentRequired = {
      x402Version: 2,
      error: "Payment required",
      resource: { url: "https://api.teardrop.dev/tools/mcp", description: "MCP gateway", mimeType: "application/json" },
      accepts: [
        {
          scheme: "exact",
          network: BASE_MAINNET,
          asset: USDC[BASE_MAINNET],
          amount: PRICES[name],
          payTo: TEARDROP_PAY_TO[0],
          maxTimeoutSeconds: 300,
          extra: { name: "USD Coin", version: "2" },
        },
      ],
    };
    if (payment === undefined) {
      return {
        content: [{ type: "text", text: JSON.stringify(paymentRequired) }],
        structuredContent: paymentRequired,
        isError: true,
      };
    }
    const auth = payment.payload.authorization;
    assert.equal(auth.to.toLowerCase(), TEARDROP_PAY_TO[0]!.toLowerCase());
    assert.equal(auth.value, PRICES[name]);
    return {
      content: [{ type: "text", text: '{"prices":[{"symbol":"ETH","price":1}]}' }],
      structuredContent: { prices: [{ symbol: "ETH", price: 1 }] },
      _meta: {
        "x402/payment-response": { success: true, transaction: TX, network: BASE_MAINNET, payer: auth.from, amount: auth.value },
      },
    };
  });
  return server;
}

describe("teardrop-mcp-pay bridge", () => {
  const calls: Array<{ name: string; paid: boolean }> = [];
  const stateDir = mkdtempSync(join(tmpdir(), "td-bridge-"));
  const ledger = new SpendLedger(join(stateDir, "bridge-ledger.jsonl"), 5_000n);
  const host = new Client({ name: "host", version: "0.0.0" });

  before(async () => {
    const settings = loadSettings("ex-bridge", { TEARDROP_STATE_DIR: stateDir });
    const account = privateKeyToAccount(generatePrivateKey());
    const guard = createGuard(settings, { budget: ledger, log: () => {} });
    const upstream = createx402MCPClient({
      name: "bridge-test",
      version: "0.0.0",
      schemes: [{ network: settings.network, client: new ExactEvmScheme(account) }],
      policies: [guard.policy],
      paymentRequirementsSelector: guard.select,
    });
    const [upClient, upServer] = InMemoryTransport.createLinkedPair();
    await fakeTeardrop(calls).connect(upServer);
    await upstream.connect(upClient);

    const [hostClient, bridgeServer] = InMemoryTransport.createLinkedPair();
    await createBridgeServer(upstream, ledger, { name: "teardrop-mcp-pay", version: "test" }, () => {}).connect(bridgeServer);
    await host.connect(hostClient);
  });

  after(async () => {
    await host.close();
  });

  it("mirrors tools with prices and without output schemas", async () => {
    const { tools } = await host.listTools();
    const tool = tools.find((t) => t.name === "get_token_price");
    assert.ok(tool);
    assert.equal(tool.outputSchema, undefined);
    assert.match(tool.description ?? "", /x402: \$0\.002000 per call/);
  });

  it("pays a tool call and appends the receipt", async () => {
    const result = (await host.callTool({ name: "get_token_price", arguments: { tokens: ["ETH"] } })) as CallToolResult;
    assert.ok(!result.isError, JSON.stringify(result.content));
    const texts = result.content.map((c) => (c.type === "text" ? c.text : ""));
    assert.ok(texts.some((t) => t.includes("prices")));
    assert.ok(texts.some((t) => t.includes(`https://basescan.org/tx/${TX}`)));
    assert.equal(ledger.spentLast24h(), 2_000n);
    assert.deepEqual(calls.slice(-2), [
      { name: "get_token_price", paid: false },
      { name: "get_token_price", paid: true },
    ]);
  });

  it("refuses a price above the per-call cap without signing", async () => {
    const before = calls.length;
    const result = (await host.callTool({ name: "get_wallet_positions", arguments: {} })) as CallToolResult;
    assert.equal(result.isError, true);
    assert.match(JSON.stringify(result.content), /refused to pay.*MAX_PER_CALL_USDC/);
    assert.deepEqual(calls.slice(before), [{ name: "get_wallet_positions", paid: false }]);
  });

  it("stops at the daily cap persisted in the ledger", async () => {
    await host.callTool({ name: "get_token_price", arguments: { tokens: ["ETH"] } });
    const result = (await host.callTool({ name: "get_token_price", arguments: { tokens: ["ETH"] } })) as CallToolResult;
    assert.equal(result.isError, true);
    assert.match(JSON.stringify(result.content), /daily cap/);
    assert.equal(ledger.spentLast24h(), 4_000n);
    assert.ok(existsSync(ledger.path));
    assert.equal(readFileSync(ledger.path, "utf8").trim().split("\n").length, 4);
  });
});
