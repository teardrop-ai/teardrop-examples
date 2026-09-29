import { chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

import type { PayeeTrust } from "./guard.js";

/** Payees shipped with each release for Teardrop's production API. Review SECURITY.md before editing. */
export const TEARDROP_PAY_TO: readonly string[] = ["0xF2Eec9De86274913F85A8aA6427Ad65a9B0bC90a"];
export const TEARDROP_HOSTS: ReadonlySet<string> = new Set(["api.teardrop.dev"]);

export interface PayToTrustOptions {
  baseUrl: string;
  /** TRUSTED_PAY_TO addresses; extends the pinned set for any host. */
  trusted: readonly string[];
  /** JSON file holding first-seen payees for hosts without a pinned set. */
  storePath: string;
  log?: (message: string) => void;
}

/**
 * Teardrop's host uses the release-pinned payee set. Any other host is trusted on
 * first use: its first challenge's payees are stored, and later changes require
 * TRUSTED_PAY_TO. Discovery documents are never consulted, because a compromised
 * server controls both the discovery document and the challenge.
 */
export class PayToTrust implements PayeeTrust {
  readonly origin: string;
  readonly #pinned: ReadonlySet<string> | undefined;

  constructor(private readonly options: PayToTrustOptions) {
    const url = new URL(options.baseUrl);
    this.origin = url.origin;
    const pinned = TEARDROP_HOSTS.has(url.hostname) ? TEARDROP_PAY_TO : [];
    const all = [...pinned, ...options.trusted].map((a) => a.toLowerCase());
    this.#pinned = all.length > 0 ? new Set(all) : undefined;
  }

  refusal(payTo: string, offered: readonly string[]): string | undefined {
    const candidate = payTo.toLowerCase();
    if (this.#pinned !== undefined) {
      return this.#pinned.has(candidate)
        ? undefined
        : `payTo ${payTo} is not pinned for ${this.origin}; if the payee legitimately changed, set TRUSTED_PAY_TO`;
    }
    const store = this.#read();
    let known = store[this.origin];
    if (known === undefined) {
      known = [...new Set(offered.map((a) => a.toLowerCase()))];
      store[this.origin] = known;
      this.#write(store);
      this.options.log?.(
        `trusting payTo ${known.join(", ")} for ${this.origin} on first use (stored in ${this.options.storePath})`,
      );
    }
    return known.includes(candidate)
      ? undefined
      : `payTo for ${this.origin} changed from ${known.join(", ")} to ${payTo}; set TRUSTED_PAY_TO to accept it`;
  }

  #read(): Record<string, string[]> {
    if (!existsSync(this.options.storePath)) return {};
    return JSON.parse(readFileSync(this.options.storePath, "utf8")) as Record<string, string[]>;
  }

  #write(store: Record<string, string[]>): void {
    mkdirSync(dirname(this.options.storePath), { recursive: true, mode: 0o700 });
    writeFileSync(this.options.storePath, `${JSON.stringify(store, null, 2)}\n`, { mode: 0o600 });
    chmodSync(this.options.storePath, 0o600);
  }
}
