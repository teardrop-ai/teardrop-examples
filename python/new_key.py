"""Create a fresh payer key in ~/.teardrop/payer.key (mode 0600) and print only its address.

uv run python -m python.new_key
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from eth_account import Account


def main() -> None:
    state_dir = Path(os.environ.get("TEARDROP_STATE_DIR", "").strip() or Path.home() / ".teardrop")
    path = state_dir / "payer.key"
    if path.exists():
        sys.exit(f"{path} already exists; refusing to overwrite it")
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    account = Account.create()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(account.key.to_0x_hex() + "\n")
    print(f"address {account.address}")
    print(f"key     {path} (mode 0600; back it up, never commit it)")
    print(f"next    send about $1 of USDC on Base to the address, then set PAYER_KEY_FILE={path}")


if __name__ == "__main__":
    main()
