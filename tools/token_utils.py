"""
token_utils.py - Utilities for handling token mints on Solana devnet.
"""

from solders.pubkey import Pubkey

# Common token mint addresses on Solana devnet
# Note: These are examples; update with actual devnet addresses if needed
DEVNET_MINTS = {
    'SOL': Pubkey.from_string('So11111111111111111111111111111111111111112'),  # Wrapped SOL
    'USDC': Pubkey.from_string('EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'),  # Mainnet USDC, may not work on devnet
    'WSOL': Pubkey.from_string('So11111111111111111111111111111111111111112'),
    # Add more tokens as needed
}

def get_mint_address(symbol: str) -> Pubkey:
    """Return the Pubkey for a given token symbol on devnet."""
    symbol_upper = symbol.upper()
    if symbol_upper in DEVNET_MINTS:
        return DEVNET_MINTS[symbol_upper]
    else:
        raise ValueError(f"Unknown token symbol: {symbol}. Please add to DEVNET_MINTS.")

def validate_mint(address: str) -> bool:
    """Validate if a string is a valid Pubkey."""
    try:
        Pubkey.from_string(address)
        return True
    except:
        return False

if __name__ == "__main__":
    # Test the functions
    print(get_mint_address('SOL'))
    print(validate_mint('So11111111111111111111111111111111111111112'))
