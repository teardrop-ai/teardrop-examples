/**
 * Plain JSON-RPC over the x402 HTTP transport. Without MCP headers the gateway
 * answers an unpaid tools/call with HTTP 402 + PAYMENT-REQUIRED; @x402/fetch signs
 * through the guard, retries with PAYMENT-SIGNATURE, and the receipt arrives in
 * PAYMENT-RESPONSE.
 */
import { ExactEvmScheme } from "@x402/evm/exact/client";
import { decodePaymentResponseHeader, wrapFetchWithPaymentFromConfig } from "@x402/fetch";
import { createGuard, explorerTx, formatUsdc, loadAccount, loadSettings, redact } from "teardrop-mcp-pay/payer";

const TOOL = "get_token_price";
const ARGS = { tokens: ["ETH"] };

async function main(): Promise<void> {
  const settings = loadSettings("ex-http");
  const account = loadAccount();
  const guard = createGuard(settings);
  console.log(`payer ${account.address} on ${settings.network}; cap ${formatUsdc(settings.maxPerCall)}/call`);

  const fetchWithPayment = wrapFetchWithPaymentFromConfig(fetch, {
    schemes: [{ network: settings.network, client: new ExactEvmScheme(account) }],
    policies: [guard.policy],
    paymentRequirementsSelector: guard.select,
  });

  const response = await fetchWithPayment(`${settings.baseUrl}/tools/mcp`, {
    method: "POST",
    headers: {
      // Accepting only JSON (no text/event-stream, no mcp-protocol-version) selects the HTTP 402 challenge.
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-Teardrop-Client": settings.clientTag,
    },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: TOOL, arguments: ARGS } }),
  });

  const body = (await response.json()) as { result?: { content?: Array<{ type: string; text?: string }>; isError?: boolean }; error?: unknown };
  if (!response.ok || body.error !== undefined || body.result?.isError) {
    throw new Error(`HTTP ${response.status}: ${JSON.stringify(body.error ?? body.result ?? body).slice(0, 500)}`);
  }
  for (const item of body.result?.content ?? []) {
    if (item.type === "text") console.log(item.text);
  }
  const header = response.headers.get("PAYMENT-RESPONSE") ?? response.headers.get("X-PAYMENT-RESPONSE");
  if (header === null) {
    if (guard.spent > 0n) throw new Error("paid, but the server sent no PAYMENT-RESPONSE header");
    console.log("no payment was needed");
    return;
  }
  const receipt = decodePaymentResponseHeader(header);
  const amount = receipt.amount ? ` ${formatUsdc(BigInt(receipt.amount))}` : "";
  console.log(`settled${amount}: ${explorerTx(receipt.network, receipt.transaction)}`);
}

main().catch((error: unknown) => {
  console.error(redact(error instanceof Error ? error.message : String(error)));
  process.exitCode = 1;
});
