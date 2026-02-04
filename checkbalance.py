from solana.rpc.api import Client
from solders.pubkey import Pubkey

PUBKEY = Pubkey.from_string("EZkGhnrTchv8jyf8fnA2A9BhswrDVSBASbJhwbbE446j")

client = Client("https://api.devnet.solana.com")
resp = client.get_balance(PUBKEY)
print(f"Balance: {resp.value / 1_000_000_000} SOL")
