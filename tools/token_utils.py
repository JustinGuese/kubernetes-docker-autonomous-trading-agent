"""
token_utils.py - Utilities for handling token mints on Solana devnet.
"""

from solders.pubkey import Pubkey

# Common token mint addresses on Solana devnet
# Updated with more accurate devnet addresses
DEVNET_MINTS = {
    'SOL': Pubkey.from_string('So11111111111111111111111111111111111111112'),  # Wrapped SOL
    'USDC': Pubkey.from_string('4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU'),  # Devnet USDC (example, verify)
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

# New function to add or update mint addresses dynamically
def add_mint_address(symbol: str, address: str):
    """Add or update a mint address in DEVNET_MINTS."""
    symbol_upper = symbol.upper()
    DEVNET_MINTS[symbol_upper] = Pubkey.from_string(address)

if __name__ == "__main__":
    # Test the functions
    print(get_mint_address('SOL'))
    print(validate_mint('So11111111111111111111111111111111111111112'))
