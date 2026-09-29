import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { CallToolRequestSchema, ListToolsRequestSchema, type CallToolResult, type Tool } from "@modelcontextprotocol/sdk/types.js";
import type { x402MCPClient } from "@x402/mcp";

import { formatUsdc, GuardRefusal } from "./guard.js";
import type { SpendLedger } from "./ledger.js";
import { explorerTx, redact } from "./payer.js";

interface TeardropPrice {
  x402?: { amount?: string };
}

/** Appends the per-call x402 price to the description once the server advertises it (_meta["teardrop/price"]). */
function describe(tool: Tool): Tool {
  // Results are forwarded without structuredContent, so an advertised outputSchema would fail host validation.
  const { outputSchema: _dropped, ...rest } = tool;
  const amount = (tool._meta?.["teardrop/price"] as TeardropPrice | undefined)?.x402?.amount;
  if (amount === undefined || !/^\d+$/.test(amount)) return rest;
  const price = `x402: ${formatUsdc(BigInt(amount))} per call`;
  return { ...rest, description: rest.description ? `${rest.description} (${price})` : price };
}

function text(message: string): CallToolResult["content"][number] {
  return { type: "text", text: message };
}

export function createBridgeServer(
  upstream: x402MCPClient,
  ledger: SpendLedger,
  info: { name: string; version: string },
  log: (message: string) => void,
): Server {
  const server = new Server(info, { capabilities: { tools: {} } });

  server.setRequestHandler(ListToolsRequestSchema, async (request) => {
    const result = await upstream.client.listTools(request.params);
    return { ...result, tools: result.tools.map(describe) };
  });

  server.setRequestHandler(CallToolRequestSchema, async (request): Promise<CallToolResult> => {
    const { name, arguments: args = {} } = request.params;
    try {
      const result = await upstream.callTool(name, args);
      const content = result.content as CallToolResult["content"];
      if (!result.paymentMade) return { content, isError: result.isError };

      const receipt = result.paymentResponse;
      if (receipt?.success && receipt.transaction) {
        const amount = BigInt(receipt.amount ?? "0");
        ledger.append({
          ts: new Date().toISOString(),
          event: "settled",
          tool: name,
          amount: amount.toString(),
          tx: receipt.transaction,
          network: receipt.network,
        });
        const note = `Paid ${formatUsdc(amount)} USDC, tx ${explorerTx(receipt.network, receipt.transaction)}; ${formatUsdc(ledger.remaining())} left in today's cap.`;
        return { content: [...content, text(note)], isError: result.isError };
      }

      ledger.append({ ts: new Date().toISOString(), event: "unsettled", tool: name, reason: "no settlement receipt" });
      log(`payment for ${name} did not settle; the signed amount still counts toward today's cap`);
      return {
        content: [text(`The payment for ${name} did not settle, so Teardrop withheld the result. Try again later.`)],
        isError: true,
      };
    } catch (error) {
      if (error instanceof GuardRefusal) {
        return {
          content: [text(`teardrop-mcp-pay refused to pay for ${name}: ${error.reasons.join("; ")}.`)],
          isError: true,
        };
      }
      const message = redact(error instanceof Error ? error.message : String(error));
      log(`tools/call ${name} failed: ${message}`);
      return { content: [text(`Calling ${name} failed: ${message}`)], isError: true };
    }
  });

  return server;
}
