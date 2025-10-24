import json
import os
from eth_abi import decode
from web3 import Web3
from token_pricing import build_exo_price_map

# Infura URL for address and token matching
INFURA_URL = os.environ["INFURA_URL"]
w3 = Web3(Web3.HTTPProvider(INFURA_URL))

# UniswapV2 Router02
KNOWN_ADDRESSES = {
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d"
}

# Metadata ABI
ERC20_ABI = [
    {
        "type": "function",
        "stateMutability": "view",
        "name": "symbol",
        "inputs": [],
        "outputs": [{"name": "", "type": "string"}],
    },
    {
        "type": "function",
        "stateMutability": "view",
        "name": "name",
        "inputs": [],
        "outputs": [{"name": "", "type": "string"}],
    },
    {
        "type": "function",
        "stateMutability": "view",
        "name": "decimals",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint8"}],
    },
]

# Load and filter mempool dump obtained from snapshot script
with open("sample.dump", "r") as f:
    data = json.load(f)

pending = data["result"]["pending"]
filtered = []

for sender, txs in pending.items():
    for nonce, tx in txs.items():
        to_addr = tx.get("to")
        if to_addr and to_addr.lower() in KNOWN_ADDRESSES:
            filtered.append(tx)

print(f"Found {len(filtered)} Uniswap transactions")

# Decode first swapExactETHForTokens call
SWAP_FUNCTIONS = {
    "0x7ff36ab5": {  # swapExactETHForTokens
        "name": "swapExactETHForTokens",
        "inputs": [
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
    },
    "0xfb3bdb41": {  # swapETHForExactTokens
        "name": "swapETHForExactTokens",
        "inputs": [
            {"name": "amountOut", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
    },
    "0x38ed1739": {  # swapExactTokensForTokens
        "name": "swapExactTokensForTokens",
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
    },
    "0x8803dbee": {  # swapTokensForExactTokens
        "name": "swapTokensForExactTokens",
        "inputs": [
            {"name": "amountOut", "type": "uint256"},
            {"name": "amountInMax", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
    },
    "0x18cbafe5": {  # swapExactTokensForETH
        "name": "swapExactTokensForETH",
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
    },
    "0x4a25d94a": {  # swapTokensForExactETH
        "name": "swapTokensForExactETH",
        "inputs": [
            {"name": "amountOut", "type": "uint256"},
            {"name": "amountInMax", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
    },
    "0xb6f9de95": {  # swapExactETHForTokensSupportingFeeOnTransferTokens
        "name": "swapExactETHForTokensSupportingFeeOnTransferTokens",
        "inputs": [
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
    },
    "0x791ac947": {  # swapExactTokensForETHSupportingFeeOnTransferTokens
        "name": "swapExactTokensForETHSupportingFeeOnTransferTokens",
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
    },
    "0xded9382a": {  # swapExactTokensForTokensSupportingFeeOnTransferTokens
        "name": "swapExactTokensForTokensSupportingFeeOnTransferTokens",
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
    },
}

# Fetch ERC20 metadata of a token
def describe_token(addr):
    addr = w3.to_checksum_address(addr)
    token = w3.eth.contract(address=addr, abi=ERC20_ABI)

    def safe_call(func):
        try:
            val = func.call()
            # decode bytes32 -> string if needed
            if isinstance(val, (bytes, bytearray)):
                val = val.split(b"\x00", 1)[0].decode(errors="ignore")
            return val
        except Exception:
            return None

    symbol = safe_call(token.functions.symbol)
    name = safe_call(token.functions.name)
    decimals = safe_call(token.functions.decimals)

    return {
        "address": addr,
        "symbol": symbol or "UNKNOWN",
        "name": name or "UNKNOWN",
        "decimals": decimals,
    }

# Decoding exogenous prices from exchange
from token_pricing import build_exo_price_map

decoded_swaps = []
token_addresses = set()

total_txs = len(filtered)
print(f"Starting decode for {total_txs} transactions...")

for idx, tx in enumerate(filtered, start=1):
    input_data = tx["input"]
    fn_selector = input_data[:10]
    call_data = input_data[10:]

    if idx % 10 == 0 or idx == total_txs:
        print(f"Progress: {idx}/{total_txs} ({idx/total_txs*100:.1f}%)")

    try:
        if fn_selector not in SWAP_FUNCTIONS:
            # Attempt dynamic lookup using 4byte.directory to resolve unknown function selectors
            import requests
            try:
                url = f"https://www.4byte.directory/api/v1/signatures/?hex_signature={fn_selector}"
                res = requests.get(url, timeout=5)
                if res.status_code == 200:
                    results = res.json().get("results", [])
                    if results:
                        print(f"Resolved {fn_selector} -> {results[0]['text_signature']}")
                    else:
                        print(f"No match found for {fn_selector} in 4byte directory")
                else:
                    print(f"Selector lookup failed ({res.status_code}): {res.text}")
            except Exception as lookup_err:
                print(f"Selector lookup error for {fn_selector}: {lookup_err}")
            continue

        abi_entry = SWAP_FUNCTIONS[fn_selector]
        payload_bytes = bytes.fromhex(call_data)
        expected_types = [inp["type"] for inp in abi_entry["inputs"]]

        try:
            decoded = decode(expected_types, payload_bytes)
        except Exception as inner_e:
            print(f"Selector {fn_selector}: decode exception {type(inner_e).__name__}: {inner_e}")
            continue

    except Exception as e:
        print(f"Decode error ({tx.get('hash','?')}): {type(e).__name__}: {e}")
        continue

    decoded_args = {
        abi_entry["inputs"][i]["name"]: decoded[i]
        for i in range(len(decoded))
    }

    path = decoded_args["path"]

    token_metas = []
    for addr in path:
        tinfo = describe_token(addr)
        token_metas.append(tinfo)
        token_addresses.add(addr.lower())

    # dynamically include all decoded arguments without assuming field names
    trade = {"function": abi_entry["name"]}
    for k, v in decoded_args.items():
        if isinstance(v, bytes):
            try:
                v = v.hex()
            except Exception:
                v = str(v)
        trade[k] = v

    # carry over gas-related fields from mempool tx
    def _hex_to_int(x):
        if x is None:
            return None
        if isinstance(x, int):
            return x
        if isinstance(x, str):
            try:
                return int(x, 16) if x.startswith("0x") else int(x)
            except Exception:
                return None
        return None

    gas_limit = _hex_to_int(tx.get("gas"))
    gas_price = _hex_to_int(tx.get("gasPrice"))
    max_fee_per_gas = _hex_to_int(tx.get("maxFeePerGas"))
    max_priority_fee_per_gas = _hex_to_int(tx.get("maxPriorityFeePerGas"))
    tx_type = _hex_to_int(tx.get("type")) if tx.get("type") is not None else None

    # Estimate effective gas price for EIP-1559 transactions
    effective_gas_price = None
    if gas_price:
        effective_gas_price = gas_price
    else:
        try:
            latest_block = w3.eth.get_block("latest")
            base_fee = latest_block.get("baseFeePerGas")
        except Exception:
            base_fee = None
        if base_fee is not None:
            eff = (base_fee or 0) + (max_priority_fee_per_gas or 0)
            effective_gas_price = min(max_fee_per_gas or eff, eff)
        else:
            # Fallback when base fee unavailable: use maxFeePerGas or priority fee
            effective_gas_price = max_fee_per_gas or max_priority_fee_per_gas

    trade.update({
        "gas": gas_limit,
        "gasPrice": gas_price,
        "maxFeePerGas": max_fee_per_gas,
        "maxPriorityFeePerGas": max_priority_fee_per_gas,
        "type": tx_type,
        "effectiveGasPrice": effective_gas_price,
        "hash": tx.get("hash"),
        "from": tx.get("from"),
        "to_router": tx.get("to"),
        "nonce": _hex_to_int(tx.get("nonce")),
        "value": _hex_to_int(tx.get("value")),
    })

    trade["path"] = token_metas

    decoded_swaps.append(trade)

# build exogenous pricing map using Coingecko
tokens_dict = {addr: describe_token(addr) for addr in token_addresses}
exo_map = build_exo_price_map(tokens_dict)

for trade in decoded_swaps:
    symbols = [t["symbol"] for t in trade["path"]]
    usd_values = [exo_map.get(s, "N/A") for s in symbols]
    trade["usd_values"] = dict(zip(symbols, usd_values))

with open("decoded_swaps.json", "w") as f:
    json.dump(decoded_swaps, f, indent=2)

print(f"Decoded {len(decoded_swaps)} transactions and wrote to decoded_swaps.json")
print(f"Exogenous mapping: {len(exo_map)} tokens priced")
