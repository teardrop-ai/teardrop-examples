/**
 * The guarded payer: every TypeScript example and the bridge sign through this
 * guard, and nothing signs outside it. Python mirrors these rules in
 * python/_shared/payer.py; keep the two in sync.
 */

export const BASE_MAINNET = "eip155:8453" as const;
export const BASE_SEPOLIA = "eip155:84532" as const;

export const USDC: Readonly<Record<string, string>> = {
  [BASE_MAINNET]: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
  [BASE_SEPOLIA]: "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
};

export const MAX_TIMEOUT_SECONDS = 300;

/** Structural subset of x402 v2 PaymentRequirements that the guard inspects. */
export interface Requirement {
  scheme: string;
  network: string;
  asset: string;
  amount: string;
  payTo: string;
  maxTimeoutSeconds: number;
  extra?: Record<string, unknown>;
}

/** Decides whether a payee address is trusted for the configured server. */
export interface PayeeTrust {
  refusal(payTo: string, offered: readonly string[]): string | undefined;
}

/** Extra spend budget beyond the in-process session total (e.g. the bridge's daily ledger). */
export interface Budget {
  remaining(): bigint;
  commit(requirement: Requirement, amount: bigint): void;
}

export interface GuardOptions {
  network: string;
  trust: PayeeTrust;
  maxPerCall: bigint;
  maxTotal: bigint;
  allowUpto?: boolean;
  confirmAbove?: bigint;
  budget?: Budget;
  onCommit?: (requirement: Requirement, amount: bigint) => void;
}

export class GuardRefusal extends Error {
  constructor(readonly reasons: readonly string[]) {
    super(`payment refused by guard: ${reasons.join("; ")}`);
    this.name = "GuardRefusal";
  }
}

export function formatUsdc(atomic: bigint): string {
  const sign = atomic < 0n ? "-" : "";
  const abs = atomic < 0n ? -atomic : atomic;
  return `${sign}$${abs / 1_000_000n}.${(abs % 1_000_000n).toString().padStart(6, "0")}`;
}

export class PaymentGuard {
  #spent = 0n;

  constructor(private readonly options: GuardOptions) {}

  get spent(): bigint {
    return this.#spent;
  }

  /** Returns why `requirement` must not be signed, or undefined if it may be. */
  refusal(requirement: Requirement, offered: readonly string[] = [requirement.payTo]): string | undefined {
    const o = this.options;
    if (requirement.network !== o.network) {
      return `network ${requirement.network} is not the configured network ${o.network}`;
    }
    const usdc = USDC[o.network];
    if (usdc === undefined || requirement.asset.toLowerCase() !== usdc.toLowerCase()) {
      return `asset ${requirement.asset} is not USDC on ${o.network}`;
    }
    if (requirement.scheme === "upto") {
      if (!o.allowUpto) return "scheme upto is opt-in; set ALLOW_UPTO=1 after approving Permit2";
    } else if (requirement.scheme !== "exact") {
      return `scheme ${requirement.scheme} is not supported`;
    } else {
      const method = requirement.extra?.assetTransferMethod;
      if (method !== undefined && method !== "eip3009") {
        return `exact via ${String(method)} is not supported; only EIP-3009 authorizations are signed`;
      }
    }
    if (!Number.isInteger(requirement.maxTimeoutSeconds) || requirement.maxTimeoutSeconds > MAX_TIMEOUT_SECONDS) {
      return `maxTimeoutSeconds ${requirement.maxTimeoutSeconds} exceeds ${MAX_TIMEOUT_SECONDS}`;
    }
    if (!/^\d+$/.test(requirement.amount)) {
      return `amount ${JSON.stringify(requirement.amount)} is not an integer atomic value`;
    }
    const amount = BigInt(requirement.amount);
    if (amount > o.maxPerCall) {
      return `amount ${formatUsdc(amount)} exceeds MAX_PER_CALL_USDC=${o.maxPerCall} (${formatUsdc(o.maxPerCall)})`;
    }
    if (o.confirmAbove !== undefined && amount > o.confirmAbove) {
      return (
        `amount ${formatUsdc(amount)} is above CONFIRM_ABOVE_USDC=${o.confirmAbove}; ` +
        "ask the user to raise CONFIRM_ABOVE_USDC if they approve this price"
      );
    }
    if (this.#spent + amount > o.maxTotal) {
      return `session total would reach ${formatUsdc(this.#spent + amount)}, above MAX_TOTAL_USDC=${o.maxTotal}`;
    }
    if (o.budget !== undefined && amount > o.budget.remaining()) {
      return `daily cap reached: ${formatUsdc(o.budget.remaining())} left, ${formatUsdc(amount)} requested`;
    }
    return o.trust.refusal(requirement.payTo, offered);
  }

  /** x402 PaymentPolicy: keeps acceptable requirements, or throws with every reason if none are. */
  readonly policy = <R extends Requirement>(_x402Version: number, requirements: R[]): R[] => {
    const offered = [...new Set(requirements.map((r) => r.payTo))];
    const reasons: string[] = [];
    const accepted = requirements.filter((r) => {
      const reason = this.refusal(r, offered);
      if (reason !== undefined) reasons.push(reason);
      return reason === undefined;
    });
    if (accepted.length === 0) throw new GuardRefusal([...new Set(reasons)]);
    // With ALLOW_UPTO=1 both schemes may pass; exact never needs a Permit2 allowance, so it goes first.
    return accepted.sort((a, b) => Number(a.scheme !== "exact") - Number(b.scheme !== "exact"));
  };

  /** x402 requirements selector: re-checks the first acceptable requirement and commits its amount. */
  readonly select = <R extends Requirement>(_x402Version: number, requirements: R[]): R => {
    const chosen = requirements[0];
    if (chosen === undefined) throw new GuardRefusal(["no payment requirements offered"]);
    const reason = this.refusal(chosen);
    if (reason !== undefined) throw new GuardRefusal([reason]);
    const amount = BigInt(chosen.amount);
    this.#spent += amount;
    this.options.budget?.commit(chosen, amount);
    this.options.onCommit?.(chosen, amount);
    return chosen;
  };
}
