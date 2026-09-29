"""Regenerate the README price table from the public /marketplace/catalog.

uv run python -m python.price_table          # rewrite README.md in place
uv run python -m python.price_table --check  # exit 1 if README.md is stale
"""

from __future__ import annotations

import argparse
import sys

import httpx

from ._shared.config import REPO_ROOT, format_usdc, load_settings

README = REPO_ROOT / "README.md"
START = "<!-- price-table:start -->"
END = "<!-- price-table:end -->"
# Mirrors the gateway's _ANON_FREE_TOOLS: free for anonymous callers, 60 calls/minute per IP.
ANON_FREE = frozenset({"calculate", "get_datetime", "count_text_stats", "discover_agents"})


def fetch_platform_tools(base_url: str) -> list[dict]:
    tools: list[dict] = []
    cursor = None
    with httpx.Client(base_url=base_url, timeout=30) as http:
        while True:
            params = {"org_slug": "platform", "sort": "price_asc", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            response = http.get("/marketplace/catalog", params=params)
            response.raise_for_status()
            page = response.json()
            tools.extend(page["tools"])
            cursor = page.get("next_cursor")
            if not cursor:
                return tools


def render(tools: list[dict]) -> str:
    rows = [
        "| Tool | Price per call (atomic) | What it does |",
        "|---|---|---|",
    ]
    for tool in sorted(tools, key=lambda t: (t["cost_usdc"], t["tool_name"])):
        cost = int(tool["cost_usdc"])
        if cost > 0:
            price = f"{format_usdc(cost)} ({cost:,})"
        elif tool["tool_name"] in ANON_FREE:
            price = "free (60/min per IP)"
        else:
            price = "flat x402 default"
        description = " ".join(str(tool.get("short_description") or tool.get("description") or "").split())
        rows.append(f"| `{tool['tool_name']}` | {price} | {description.replace('|', '/')} |")
    return "\n".join(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail if README.md is out of date")
    args = parser.parse_args()

    settings = load_settings("other")
    table = render(fetch_platform_tools(settings.base_url))
    readme = README.read_text(encoding="utf-8")
    head, _, rest = readme.partition(START)
    _, _, tail = rest.partition(END)
    updated = f"{head}{START}\n{table}\n{END}{tail}"
    if args.check:
        if updated != readme:
            sys.exit("README price table is stale; run: uv run python -m python.price_table")
        return
    README.write_text(updated, encoding="utf-8")
    print(f"wrote {len(table.splitlines()) - 2} tools to {README}")


if __name__ == "__main__":
    main()
