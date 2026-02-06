#!/usr/bin/env python3
"""Emergency tool to withdraw nearly all mainnet funds to a recovery wallet.

This script is intentionally simple and explicit. It is NOT called by the
autonomous agent; you run it manually when you want to pull funds out of the
bot wallet.
"""

from __future__ import annotations

import sys
from typing import NoReturn

from core.config import load_config
from tools.wallet_tool import WalletTool

# TODO: Replace this with your own safe recovery wallet address before use.
RECOVERY_ADDRESS = "PASTE_YOUR_SAFE_WALLET_ADDRESS_HERE"


def _die(msg: str) -> NoReturn:
    print(f"ERROR: {msg}")
    sys.exit(1)


def main() -> None:
    if RECOVERY_ADDRESS == "PASTE_YOUR_SAFE_WALLET_ADDRESS_HERE":
        _die("Update RECOVERY_ADDRESS in tools/emergency_withdraw.py before use.")

    config = load_config()

    # Sanity check: only operate on mainnet.
    rpc_url = config.solana.rpc_url or ""
    if "mainnet" not in rpc_url.lower():
        _die(f"Not connected to mainnet (SOLANA_RPC_URL={rpc_url!r})")

    wallet = WalletTool(config.solana.private_key, rpc_url)
    balance = wallet.balance_sol()

    print("=" * 60)
    print("EMERGENCY WITHDRAWAL")
    print("=" * 60)
    print(f"Current balance: {balance:.6f} SOL")
    print(f"Recovery address: {RECOVERY_ADDRESS}")
    print(f"RPC URL: {rpc_url}")
    print("=" * 60)

    if balance < 0.001:
        print("Balance too low to withdraw (< 0.001 SOL). Nothing to do.")
        return

    # Leave a small amount for rent / residual fees.
    amount = balance - 0.001
    if amount <= 0:
        print("Computed withdrawal amount is non-positive; aborting.")
        return

    print(f"\nWithdraw {amount:.6f} SOL to the recovery wallet?")
    confirm = input("Type 'YES' to confirm: ")
    if confirm.strip() != "YES":
        print("Cancelled.")
        return

    print("\nSending transaction...")
    try:
        sig = wallet.send(RECOVERY_ADDRESS, amount, confirm=True)
        print(f"✓ Withdrawn {amount:.6f} SOL")
        print(f"✓ Signature: {sig}")
        print(f"✓ View on Solscan: https://solscan.io/tx/{sig}")
    except Exception as exc:  # pragma: no cover - best-effort logging
        print(f"✗ Transaction failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()

