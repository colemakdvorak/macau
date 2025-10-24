import json
import os
from web3 import Web3
from typing import Dict

# Connect to an Ethereum RPC endpoint (Infura preferred, fallback to QuickNode)
PRIMARY_RPC = os.getenv("INFURA_URL")
SECONDARY_RPC = os.getenv("QUICKNODE_ENDPOINT")

# Prefer QuickNode first to avoid intermittent Infura DNS/rate issues, then fall back to Infura
rpc_candidates = [u for u in [SECONDARY_RPC, PRIMARY_RPC] if u]
w3 = None
RPC_URL = None

for uri in rpc_candidates:
    try:
        provider = Web3.HTTPProvider(uri, request_kwargs={"timeout": 20})
        candidate = Web3(provider)
        if candidate.is_connected():
            w3 = candidate
            RPC_URL = uri
            break
    except Exception:
        continue

if w3 is None or not w3.is_connected():
    raise RuntimeError("No Ethereum RPC reachable. Set INFURA_URL or QUICKNODE_ENDPOINT.")

# Uniswap V2 Router and Factory addresses
UNISWAP_FACTORY = Web3.to_checksum_address("0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f")
WETH_ADDRESS = Web3.to_checksum_address("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")

# Uniswap Factory ABI (minimal for fetching pair addresses)
FACTORY_ABI = [
    {
        "constant": True,
        "inputs": [
            {"internalType": "address", "name": "", "type": "address"},
            {"internalType": "address", "name": "", "type": "address"},
        ],
        "name": "getPair",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    }
]

# Uniswap Pair ABI (minimal subset)
PAIR_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "getReserves",
        "outputs": [
            {"internalType": "uint112", "name": "_reserve0", "type": "uint112"},
            {"internalType": "uint112", "name": "_reserve1", "type": "uint112"},
            {"internalType": "uint32", "name": "_blockTimestampLast", "type": "uint32"},
        ],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {"constant": True, "inputs": [], "name": "token0", "outputs": [{"type": "address"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "token1", "outputs": [{"type": "address"}], "type": "function"},
]


# Minimal ERC20 ABI for decimals
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    }
]

def get_decimals(token_address: str) -> int:
    try:
        erc20 = w3.eth.contract(address=token_address, abi=ERC20_ABI)
        return erc20.functions.decimals().call()
    except Exception:
        # Default to 18 if decimals call fails
        return 18


def fetch_token_price_in_weth(token_address: str) -> float:
    """Fetches token price in WETH from Uniswap V2"""
    factory = w3.eth.contract(address=UNISWAP_FACTORY, abi=FACTORY_ABI)
    pair_address = factory.functions.getPair(token_address, WETH_ADDRESS).call()

    if pair_address == "0x0000000000000000000000000000000000000000":
        print(f"No Uniswap pair found for {token_address}")
        return None

    pair_contract = w3.eth.contract(address=pair_address, abi=PAIR_ABI)
    token0 = pair_contract.functions.token0().call()
    token1 = pair_contract.functions.token1().call()
    reserves = pair_contract.functions.getReserves().call()

    if token0.lower() == token_address.lower():
        reserve_token, reserve_weth = reserves[0], reserves[1]
    else:
        reserve_token, reserve_weth = reserves[1], reserves[0]

    if reserve_token == 0 or reserve_weth == 0:
        return None

    token_decimals = get_decimals(token_address)
    weth_decimals = 18
    # price_in_weth = (WETH_reserve / 10^18) / (token_reserve / 10^decimals)
    price_in_weth = (reserve_weth / (10 ** weth_decimals)) / (reserve_token / (10 ** token_decimals))
    return price_in_weth


def fetch_token_price_in_usdc(token_address: str) -> float:
    """Fetch token price directly in USDC from Uniswap V2 (fallback when no WETH pair)."""
    USDC = Web3.to_checksum_address("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48")
    factory = w3.eth.contract(address=UNISWAP_FACTORY, abi=FACTORY_ABI)
    pair_address = factory.functions.getPair(token_address, USDC).call()

    if pair_address == "0x0000000000000000000000000000000000000000":
        return None

    pair_contract = w3.eth.contract(address=pair_address, abi=PAIR_ABI)
    token0 = pair_contract.functions.token0().call()
    reserves = pair_contract.functions.getReserves().call()

    # Determine which reserve corresponds to token vs USDC
    if token0.lower() == token_address.lower():
        reserve_token, reserve_usdc = reserves[0], reserves[1]
    else:
        reserve_token, reserve_usdc = reserves[1], reserves[0]

    if reserve_token == 0 or reserve_usdc == 0:
        return None

    token_decimals = get_decimals(token_address)
    usdc_decimals = 6
    # price_in_usdc = (USDC_reserve / 10^6) / (token_reserve / 10^decimals)
    price_in_usdc = (reserve_usdc / (10 ** usdc_decimals)) / (reserve_token / (10 ** token_decimals))
    return price_in_usdc


def fetch_weth_usd() -> float:
    """Fetches WETH/USD from Uniswap V2 stable pair (WETH/USDC)"""
    USDC = Web3.to_checksum_address("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48")
    factory = w3.eth.contract(address=UNISWAP_FACTORY, abi=FACTORY_ABI)
    pair_address = factory.functions.getPair(WETH_ADDRESS, USDC).call()

    if pair_address == "0x0000000000000000000000000000000000000000":
        raise ValueError("No WETH/USDC pair found")

    pair_contract = w3.eth.contract(address=pair_address, abi=PAIR_ABI)
    token0 = pair_contract.functions.token0().call()
    reserves = pair_contract.functions.getReserves().call()

    if token0.lower() == WETH_ADDRESS.lower():
        reserve_weth, reserve_usdc = reserves[0], reserves[1]
    else:
        reserve_weth, reserve_usdc = reserves[1], reserves[0]

    # Normalize reserves by token decimals to compute USD per WETH
    usdc_decimals = 6
    weth_decimals = 18
    return (reserve_usdc / (10 ** usdc_decimals)) / (reserve_weth / (10 ** weth_decimals))


def build_exo_price_map(token_addresses: Dict[str, str]):
    """Creates and saves exo.json with prices derived from Uniswap"""
    weth_usd = fetch_weth_usd()
    exo = {}

    for symbol, address in token_addresses.items():
        # Handle nested token info dicts
        if isinstance(address, dict):
            address = address.get("address")
            if not address:
                print(f"Skipping {symbol}: no valid address field")
                continue

        cs_addr = Web3.to_checksum_address(address)
        # Special-case WETH: use WETH/USD directly
        if cs_addr.lower() == WETH_ADDRESS.lower():
            price_usd = weth_usd
        else:
            price_in_weth = fetch_token_price_in_weth(cs_addr)
            if price_in_weth is None:
                # Fallback: try direct USDC pair for tokens without WETH pool
                price_in_usdc = fetch_token_price_in_usdc(cs_addr)
                if price_in_usdc is None:
                    print(f"Skipping {symbol} (no DEX liquidity)")
                    continue
                price_usd = price_in_usdc
            else:
                price_usd = price_in_weth * weth_usd
        lower_addr = address.lower()
        decimals = get_decimals(cs_addr)
        exo[lower_addr] = {
            "symbol": symbol,
            "price_usd": price_usd,
            "decimals": decimals
        }
        print(f"{lower_addr}: {symbol} {price_usd:.10f} USD")

    # Ensure WETH is present in exo map
    if WETH_ADDRESS.lower() not in exo:
        exo[WETH_ADDRESS.lower()] = {
            "symbol": "WETH",
            "price_usd": weth_usd,
            "decimals": 18
        }

    with open("exo.json", "w") as f:
        json.dump(exo, f, indent=2)

    print(f"Saved {len(exo)} token DEX prices to exo.json")

    # Return map for compatibility with other scripts
    return exo

if __name__ == "__main__":
    # Example token list (symbol -> address)
    tokens = {
        "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "UNI": "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
        "SHIB": "0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE",
        # Add more as needed
    }

    build_exo_price_map(tokens)
