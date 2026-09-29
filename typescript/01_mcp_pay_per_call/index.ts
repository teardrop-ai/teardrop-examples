/**
 * Pay per call over MCP with @x402/mcp: tools/list, then tools/call get_token_price.
 * The gateway answers the unpaid call with an isError + structuredContent challenge;
 * the client signs it through the guard and retries with params._meta["x402/payment"].
 */
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { ExactEvmScheme } from "@x402/evm/exact/client";
import { createx402MCPClient } from "@x402/mcp";
import { createGuard, explorerTx, formatUsdc, loadAccount, loadSettings, redact } from "teardrop-mcp-pay/payer";

const TOOL = "get_token_price";
const ARGS = { tokens: ["ETH"] };

async function main(): Promise<void> {
  const settings = loadSettings("ex-ts-mcp");
  const account = loadAccount();
  const guard = createGuard(settings);
  console.log(
    `payer ${account.address} on ${settings.network}; caps ${formatUsdc(settings.maxPerCall)}/call, ` +
      `${formatUsdc(settings.maxTotal)}/session`,
  );

  const client = createx402MCPClient({
    name: "teardrop-examples-ts",
    version: "0.1.0",
    schemes: [{ network: settings.network, client: new ExactEvmScheme(account) }],
    policies: [guard.policy],
    paymentRequirementsSelector: guard.select,
    autoPayment: true,
  });
  const transport = new StreamableHTTPClientTransport(new URL(`${settings.baseUrl}/tools/mcp`), {
    requestInit: { headers: { "X-Teardrop-Client": settings.clientTag } },
  });
  await client.connect(transport);
  try {
    const { tools } = await client.listTools();
    console.log(`tools/list: ${tools.length} tools${tools.some((t) => t.name === TOOL) ? `, including ${TOOL}` : ""}`);

    const result = await client.callTool(TOOL, ARGS);
    for (const item of result.content) {
      if (item.type === "text") console.log(String(item.text));
    }
    if (result.isError) {
      throw new Error(result.paymentMade ? "payment did not settle; the result was withheld" : "tool call failed");
    }
    if (!result.paymentMade) {
      console.log("no payment was needed for this call");
      return;
    }
    const receipt = result.paymentResponse;
    if (!receipt?.transaction) throw new Error("paid call returned no settlement receipt");
    const amount = receipt.amount ? ` ${formatUsdc(BigInt(receipt.amount))}` : "";
    console.log(`settled${amount}: ${explorerTx(receipt.network, receipt.transaction)}`);
  } finally {
    await client.close();
  }
}

main().catch((error: unknown) => {
  console.error(redact(error instanceof Error ? error.message : String(error)));
  process.exitCode = 1;
});
