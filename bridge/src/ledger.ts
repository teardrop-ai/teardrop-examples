import { appendFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { dirname } from "node:path";

import type { Budget, Requirement } from "./guard.js";

const DAY_MS = 24 * 60 * 60 * 1000;

export type LedgerEntry =
  | { ts: string; event: "signed"; amount: string; payTo: string; network: string }
  | { ts: string; event: "settled"; tool: string; amount: string; tx: string; network: string }
  | { ts: string; event: "unsettled"; tool: string; reason: string };

/**
 * Append-only JSONL spend log. The daily cap counts every signed authorization in
 * the last 24 hours, settled or not, so it survives restarts and never undercounts.
 */
export class SpendLedger implements Budget {
  constructor(
    readonly path: string,
    readonly dailyCap: bigint,
    private readonly now: () => number = Date.now,
  ) {}

  spentLast24h(): bigint {
    if (!existsSync(this.path)) return 0n;
    const since = this.now() - DAY_MS;
    let total = 0n;
    for (const line of readFileSync(this.path, "utf8").split("\n")) {
      if (line.trim() === "") continue;
      const entry = JSON.parse(line) as LedgerEntry;
      if (entry.event === "signed" && Date.parse(entry.ts) > since) total += BigInt(entry.amount);
    }
    return total;
  }

  remaining(): bigint {
    const left = this.dailyCap - this.spentLast24h();
    return left > 0n ? left : 0n;
  }

  commit(requirement: Requirement, amount: bigint): void {
    this.append({
      ts: new Date(this.now()).toISOString(),
      event: "signed",
      amount: amount.toString(),
      payTo: requirement.payTo,
      network: requirement.network,
    });
  }

  append(entry: LedgerEntry): void {
    mkdirSync(dirname(this.path), { recursive: true, mode: 0o700 });
    appendFileSync(this.path, `${JSON.stringify(entry)}\n`, { mode: 0o600 });
  }
}
