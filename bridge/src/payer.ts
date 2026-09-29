import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import { privateKeyToAccount, type PrivateKeyAccount } from "viem/accounts";

import { BASE_MAINNET, BASE_SEPOLIA, formatUsdc, PaymentGuard, type Budget, type Requirement } from "./guard.js";
import { PayToTrust } from "./trust.js";

export * from "./guard.js";
export { PayToTrust, TEARDROP_HOSTS, TEARDROP_PAY_TO } from "./trust.js";

export const DEFAULT_BASE_URL = "https://api.teardrop.dev";

/** Closed allowlist for the X-Teardrop-Client header. Tags are spoofable and never affect pricing. */
export const CLIENT_TAGS = ["ex-py-mcp", "ex-ts-mcp", "ex-bridge", "ex-http", "ex-bootstrap", "ex-a2a", "ex-canary", "other"] as const;
export type ClientTag = (typeof CLIENT_TAGS)[number];

export interface Settings {
  baseUrl: string;
  network: typeof BASE_MAINNET | typeof BASE_SEPOLIA;
  maxPerCall: bigint;
  maxTotal: bigint;
  allowUpto: boolean;
  trustedPayTo: string[];
  stateDir: string;
  clientTag: ClientTag;
}

type Env = Record<string, string | undefined>;

export function atomicEnv(env: Env, name: string, fallback: bigint): bigint {
  const raw = env[name]?.trim();
  if (raw === undefined || raw === "") return fallback;
  if (!/^\d+$/.test(raw)) {
    throw new Error(`${name} must be an integer number of atomic USDC units (1000000 = $1), got ${JSON.stringify(raw)}`);
  }
  return BigInt(raw);
}

export function loadSettings(defaultTag: ClientTag, env: Env = process.env): Settings {
  const network = env.TEARDROP_NETWORK?.trim() || BASE_MAINNET;
  if (network !== BASE_MAINNET && network !== BASE_SEPOLIA) {
    throw new Error(`TEARDROP_NETWORK must be ${BASE_MAINNET} or ${BASE_SEPOLIA}, got ${network}`);
  }
  const tag = env.TEARDROP_CLIENT_TAG?.trim() || defaultTag;
  const clientTag: ClientTag = (CLIENT_TAGS as readonly string[]).includes(tag) ? (tag as ClientTag) : "other";
  return {
    baseUrl: (env.TEARDROP_BASE_URL?.trim() || DEFAULT_BASE_URL).replace(/\/+$/, ""),
    network,
    maxPerCall: atomicEnv(env, "MAX_PER_CALL_USDC", 10_000n),
    maxTotal: atomicEnv(env, "MAX_TOTAL_USDC", 100_000n),
    allowUpto: env.ALLOW_UPTO === "1",
    trustedPayTo: (env.TRUSTED_PAY_TO ?? "")
      .split(",")
      .map((a) => a.trim())
      .filter((a) => a !== ""),
    stateDir: env.TEARDROP_STATE_DIR?.trim() || join(homedir(), ".teardrop"),
    clientTag,
  };
}

const secrets = new Set<string>();

/** Removes the loaded private key from text before it is printed. */
export function redact(text: string): string {
  let out = text;
  for (const secret of secrets) {
    out = out.replace(new RegExp(`(0x)?${secret}`, "gi"), "[redacted]");
  }
  return out;
}

/** Reads the payer key from PAYER_PRIVATE_KEY or PAYER_KEY_FILE. The key is never logged. */
export function loadAccount(env: Env = process.env): PrivateKeyAccount {
  const file = env.PAYER_KEY_FILE?.trim();
  const raw = (env.PAYER_PRIVATE_KEY?.trim() || (file ? readFileSync(file, "utf8") : "")).trim();
  if (raw === "") throw new Error("set PAYER_KEY_FILE (preferred) or PAYER_PRIVATE_KEY; see SECURITY.md");
  const hex = raw.replace(/^0x/i, "");
  if (!/^[0-9a-fA-F]{64}$/.test(hex)) throw new Error("payer key must be 32 bytes of hex (optionally 0x-prefixed)");
  secrets.add(hex.toLowerCase());
  return privateKeyToAccount(`0x${hex}`);
}

export interface GuardExtras {
  budget?: Budget;
  confirmAbove?: bigint;
  log?: (message: string) => void;
}

export function createGuard(settings: Settings, extras: GuardExtras = {}): PaymentGuard {
  const log = extras.log ?? ((message: string) => console.error(message));
  return new PaymentGuard({
    network: settings.network,
    maxPerCall: settings.maxPerCall,
    maxTotal: settings.maxTotal,
    allowUpto: settings.allowUpto,
    confirmAbove: extras.confirmAbove,
    budget: extras.budget,
    trust: new PayToTrust({
      baseUrl: settings.baseUrl,
      trusted: settings.trustedPayTo,
      storePath: join(settings.stateDir, "payto.json"),
      log,
    }),
    onCommit: (r: Requirement, amount: bigint) =>
      log(`signing ${formatUsdc(amount)} USDC (${r.scheme}) to ${r.payTo} on ${r.network}`),
  });
}

export function explorerTx(network: string, tx: string): string {
  return network === BASE_SEPOLIA ? `https://sepolia.basescan.org/tx/${tx}` : `https://basescan.org/tx/${tx}`;
}
