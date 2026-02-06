# Mainnet Wallet Setup Guide

⚠️ **WARNING: REAL MONEY** ⚠️

Running the bot on Solana mainnet uses real SOL and real dollars. Read this
guide carefully and only proceed with funds you can afford to lose.

## Prerequisites

- [ ] You have tested thoroughly on devnet.
- [ ] You understand the risks of self-custody and DeFi.
- [ ] You have a separate recovery wallet that is NOT used by the bot.

## Step 1: Create a Dedicated Mainnet Wallet

Create a fresh wallet that will be used exclusively by the bot.

```bash
solana-keygen new --outfile ~/.config/solana/mainnet-bot.json
```

Alternatively, you can export a private key from a wallet like Phantom or
Solflare, but it is strongly recommended to use a dedicated wallet that does
not hold your primary funds.

## Step 2: Fund the Wallet

Initial funding recommendations:

- **Minimum**: 0.5 SOL
  - ~0.1 SOL: rent + gas buffer (safety minimum)
  - ~0.4 SOL: trading capital
- **Recommended for testing**: 1–2 SOL

Transfer SOL from your primary wallet or an exchange to the bot wallet.

## Step 3: Get a Jupiter Ultra API Key

Mainnet swaps use the Jupiter Ultra API, which requires an API key.

1. Visit `https://portal.jup.ag`
2. Create an account (email-based)
3. Generate an API key
4. Copy the key; you will use it in your `.env`

## Step 4: Configure Environment for Mainnet

Update your `.env` to point at mainnet and enable Ultra:

```bash
# Network
SOLANA_PRIVATE_KEY=<mainnet-wallet-base58-private-key>
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
JUPITER_API_KEY=<your-jupiter-ultra-api-key>

# Mainnet safety controls
SOLANA_MAINNET_MIN_BALANCE=0.1     # Minimum SOL to keep after swaps (rent + gas buffer)

# Policy caps (conservative defaults)
MAX_SOL_PER_TX=0.1
DAILY_SPEND_CAP_SOL=0.5
```

The bot enforces:

- Per-transaction SOL caps (`MAX_SOL_PER_TX`).
- Daily SOL spend caps (`DAILY_SPEND_CAP_SOL`).
- USD-equivalent swap caps from `PolicyConfig`.
- A **mainnet SOL balance floor** (`SOLANA_MAINNET_MIN_BALANCE`) so swaps cannot
  drain the wallet below a safety threshold.

There is **no manual approval file**. Once configured, the bot has autonomy to
trade within these limits.

## Step 5: Dry Run First

Always run a dry run before letting the bot execute real swaps:

```bash
python main.py --dry-run
```

Confirm:

- [ ] The wallet address is the expected mainnet bot wallet.
- [ ] The reported balance matches your expectations.
- [ ] Proposed swaps and amounts look reasonable.
- [ ] Safety limits (caps and min balance) are correctly configured.

No on-chain transactions are sent in dry-run mode.

## Step 6: Run on Mainnet

When you are satisfied with the configuration and dry-run behavior:

```bash
python main.py
```

On mainnet the bot will:

1. Observe markets and on-chain state.
2. Decide whether to act (including performing swaps) based on its policies.
3. Execute swaps via Jupiter Ultra when appropriate.
4. Respect configured caps and the mainnet balance floor.
5. Record an audit entry for each successful mainnet swap.

## Step 7: Inspect Mainnet Transaction Log

Mainnet swap activity is recorded in the JSON memory store.

```bash
cat memory/state.json | jq '.mainnet_transactions'
```

Each entry includes:

- Timestamp and date
- Transaction type (e.g. `"swap"`)
- Details: tokens, amounts, signature, prices, slippage
- Chain identifier (`"solana-mainnet"`)

You can use the signature with explorers like:

```text
https://solscan.io/tx/<signature>
```

## Step 8: Emergency Withdraw

If you need to quickly move funds out of the bot wallet, use the emergency
withdraw tool.

```bash
python tools/emergency_withdraw.py
```

The script will:

- Ensure you are connected to mainnet.
- Show the current balance and the configured recovery address.
- Ask you to type `YES` before sending nearly all SOL to the recovery wallet,
  leaving a small buffer for rent (0.001 SOL by default).

You can always fall back to direct CLI transfer if preferred:

```bash
solana transfer <your-recovery-wallet> ALL \
  --keypair ~/.config/solana/mainnet-bot.json \
  --url https://api.mainnet-beta.solana.com
```

## Safety Summary

Built-in safeguards:

1. **Balance Floor**: `SOLANA_MAINNET_MIN_BALANCE` prevents swaps that would
   drop SOL below a safety minimum.
2. **Per-Tx and Daily Caps**: `MAX_SOL_PER_TX` and `DAILY_SPEND_CAP_SOL` limit
   wallet_send actions.
3. **Swap USD Caps**: `PolicyConfig` limits individual swap notional and daily
   cumulative swap volume.
4. **Dry-Run Mode**: Allows you to validate behavior before sending real
   transactions.
5. **Audit Log**: `mainnet_transactions` keeps a capped history of mainnet
   swaps for review.

Even with these controls, trading remains risky. Only deposit capital you are
comfortable risking, and periodically review logs and balances.

