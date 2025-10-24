import json
from transaction import Transaction
from mev_optimization import compute_batch

# Canonical WETH address (Ethereum mainnet)
WETH_ADDRESS = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"

def infer_rate_and_qty(swap):
    fn = swap.get("function", "")
    a_in = swap.get("amountIn")
    a_out_min = swap.get("amountOutMin")
    a_out = swap.get("amountOut")
    a_in_max = swap.get("amountInMax")

    # Infer q and r based on function type semantics
    if fn in ("swapExactTokensForTokens", "swapExactETHForTokens", "swapExactTokensForETHSupportingFeeOnTransferTokens"):
        q = a_in or 1
        if a_in and a_out_min:
            r = a_out_min / a_in
        else:
            r = 1.0
    elif fn in ("swapTokensForExactTokens", "swapETHForExactTokens", "swapTokensForExactETH"):
        q = a_out or 1
        if a_out and a_in_max:
            r = a_in_max / a_out
        else:
            r = 1.0
    else:
        q = a_in or 1
        r = 1.0

    return q, r


if __name__ == "__main__":
    # Load processed mempool and exogenous price map
    with open("decoded_swaps.json") as f:
        swaps = json.load(f)
    with open("exo.json") as f:
        exo_raw = json.load(f)
    # Validate exo.json schema and build normalized address-price mapping with symbol reference
    exo = {}
    for addr, data in exo_raw.items():
        if not isinstance(data, dict) or "symbol" not in data or "price_usd" not in data:
            print(f"WARNING: Skipping malformed exo entry for {addr}: {data}")
            continue
        lower_addr = addr.lower()
        exo[lower_addr] = {
            "symbol": data["symbol"],
            "price_usd": data["price_usd"],
            "decimals": data.get("decimals", 18)
        }
    print(f"Loaded {len(exo)} token prices from exo.json")

    batch = []
    for swap in swaps:
        path = swap.get("path", [])
        if len(path) >= 2:
            src_entry = path[0]
            dst_entry = path[-1]
            src = src_entry.get("address", "").lower()
            dst = dst_entry.get("address", "").lower()
            src_symbol = src_entry.get("symbol", src)
            dst_symbol = dst_entry.get("symbol", dst)
            # Use token decimals to normalize amounts and compute q (src units) and r (dst per src)
            src_dec = exo.get(src, {}).get("decimals", 18)
            dst_dec = exo.get(dst, {}).get("decimals", 18)

            fn = swap.get("function", "")
            a_in = swap.get("amountIn")
            a_out_min = swap.get("amountOutMin")
            a_out = swap.get("amountOut")
            a_in_max = swap.get("amountInMax")

            def to_unit(x, d):
                return (x / (10 ** d)) if isinstance(x, (int, float)) else None

            a_in_n = to_unit(a_in, src_dec)
            a_out_min_n = to_unit(a_out_min, dst_dec)
            a_out_n = to_unit(a_out, dst_dec)
            a_in_max_n = to_unit(a_in_max, src_dec)

            # Compute q (in src units) and r (dst per src) strictly from on-chain amounts.
            # If amounts are missing, skip to avoid fabricating profit.
            q = None
            r = None
            if fn in ("swapExactTokensForTokens", "swapExactETHForTokens", "swapExactTokensForETH", "swapExactTokensForETHSupportingFeeOnTransferTokens"):
                # Known exact-in path: need amountIn and amountOutMin
                if a_in_n and a_out_min_n:
                    q = a_in_n
                    r = a_out_min_n / a_in_n
            elif fn in ("swapTokensForExactTokens", "swapETHForExactTokens", "swapTokensForExactETH"):
                # Known exact-out path: need amountOut and amountInMax
                if a_out_n and a_in_max_n:
                    q = a_in_max_n
                    r = a_out_n / a_in_max_n
            else:
                # Unsupported or unrecognized function signature without reliable amounts
                pass

            # Validate the implied rate against fair price to avoid artifacts from min/max bounds.
            # Clamp r into a conservative band around fair price to avoid false positives while retaining samples.
            if r is not None and r > 0:
                src_price = exo.get(src, {}).get("price_usd")
                dst_price = exo.get(dst, {}).get("price_usd")
                if src_price and dst_price and dst_price > 0:
                    r_fair = src_price / dst_price
                    tol = 0.10  # allow +/-10% deviation
                    low = r_fair * (1 - tol)
                    high = r_fair * (1 + tol)
                    if r < low:
                        r = low
                    elif r > high:
                        r = high

            # Final validation: require both q and r inferred from actual calldata amounts
            if q is None or q <= 0 or r is None or r <= 0:
                print(f"Skipping swap {src_symbol} ({src})->{dst_symbol} ({dst}): invalid or missing inference (q={q}, r={r})")
                continue

            # Compute gas fee using enriched fields
            def _coerce_int(x):
                try:
                    return int(x)
                except Exception:
                    return 0

            # Prefer effectiveGasPrice (estimated for EIP-1559) -> legacy gasPrice -> best-effort from EIP-1559 caps
            gas_price_wei = _coerce_int(swap.get("effectiveGasPrice") or swap.get("gasPrice") or 0)
            if not gas_price_wei:
                max_fee = _coerce_int(swap.get("maxFeePerGas"))
                max_prio = _coerce_int(swap.get("maxPriorityFeePerGas"))
                gas_price_wei = max_fee or max_prio or 0

            # Prefer actual used if available (for confirmed txs); else fall back to gas limit as an upper bound
            gas_used = _coerce_int(swap.get("gasUsed") or swap.get("gas") or 0)
            gas_fee_eth = (gas_price_wei * gas_used) / 1e18 if gas_price_wei and gas_used else 0.0

            tx = Transaction(src, dst, q, r)
            tx.src_symbol = src_symbol
            tx.dst_symbol = dst_symbol
            tx.gas_fee_eth = gas_fee_eth

            # estimate gas fee in USD if WETH or ETH price available
            weth_entry = next((v for k, v in exo.items() if v["symbol"] == "WETH"), None)
            if weth_entry and "price_usd" in weth_entry:
                tx.gas_fee_usd = gas_fee_eth * weth_entry["price_usd"]
            else:
                # Hardcoded fallback WETH price as of Oct 23 2025, 10:30PM (UTC+1)
                fallback_weth_price_usd = 3842.42
                tx.gas_fee_usd = gas_fee_eth * fallback_weth_price_usd

            batch.append(tx)

    # Filter out transactions missing exo data (address-based lookup)
    valid_batch = []
    for tx in batch:
        if tx.src in exo and tx.dst in exo:
            valid_batch.append(tx)
        else:
            src_sym = getattr(tx, "src_symbol", tx.src)
            dst_sym = getattr(tx, "dst_symbol", tx.dst)
            print(f"Skipping {src_sym} ({tx.src})->{dst_sym} ({tx.dst}) (missing exo price data)")

    print(f"Running MEV optimization on {len(valid_batch)} valid transactions...")

    # Extract price map for optimizer (pure address: price_usd)
    exo_numeric = {addr: data["price_usd"] for addr, data in exo.items()}
    results = compute_batch(valid_batch, exo_numeric, base_asset=WETH_ADDRESS.lower())

    # Serialize final results with missed gas metrics
    serializable = {}
    # Global aggregates
    total_profit_usd = 0.0
    total_included_gas_usd = 0.0
    total_missed_gas_usd = 0.0
    pairs_total = 0
    pairs_executed = 0
    executed_tx_total = 0
    candidate_tx_total = 0

    for pair, info in results.items():
        base, other = pair

        # All candidate txs for this pair (both directions)
        candidates = [
            t for t in valid_batch
            if (t.src == base and t.dst == other) or (t.src == other and t.dst == base)
        ]

        executed_list = info.get("executed") or []

        # Sum gas paid by executed txs (mediator has None, excluded by guard)
        included_gas_eth = sum(
            (getattr(t, "gas_fee_eth", 0.0) or 0.0)
            for t in executed_list
            if getattr(t, "gas_fee_eth", None)
        )
        included_gas_usd = sum(
            (getattr(t, "gas_fee_usd", 0.0) or 0.0)
            for t in executed_list
            if getattr(t, "gas_fee_usd", None)
        )

        # Sum gas across all candidate txs for the pair
        total_candidate_gas_eth = sum(
            (getattr(t, "gas_fee_eth", 0.0) or 0.0)
            for t in candidates
            if getattr(t, "gas_fee_eth", None)
        )
        total_candidate_gas_usd = sum(
            (getattr(t, "gas_fee_usd", 0.0) or 0.0)
            for t in candidates
            if getattr(t, "gas_fee_usd", None)
        )

        # Missed gas is the gas not included by the executed subset
        missed_gas_eth = max(total_candidate_gas_eth - included_gas_eth, 0.0)
        missed_gas_usd = max(total_candidate_gas_usd - included_gas_usd, 0.0)

        # Profit from optimizer is in USD (uses exo prices); compute net after included gas
        # Update global aggregates and counts
        executed_real = [t for t in executed_list if getattr(t, "gas_fee_eth", None) is not None]
        executed_count = len(executed_real)
        candidate_count = len(candidates)

        total_profit_usd += (info.get("profit") or 0.0)
        total_included_gas_usd += included_gas_usd
        total_missed_gas_usd += missed_gas_usd
        pairs_total += 1
        if executed_real:
            pairs_executed += 1
        executed_tx_total += executed_count
        candidate_tx_total += candidate_count

        net_profit_after_included_gas_usd = (info.get("profit") or 0.0) - included_gas_usd

        serializable[str(pair)] = {
            "decision": info.get("decision"),
            "profit": info.get("profit"),
            "net_profit_after_included_gas_usd": net_profit_after_included_gas_usd,
            "src_symbol": getattr(executed_list[0], "src_symbol", None) if executed_list else None,
            "dst_symbol": getattr(executed_list[-1], "dst_symbol", None) if executed_list else None,
            # Gas paid by executed subset
            "included_gas_eth": included_gas_eth,
            "included_gas_usd": included_gas_usd,
            # Total candidate gas and missed opportunity
            "total_candidate_gas_eth": total_candidate_gas_eth,
            "total_candidate_gas_usd": total_candidate_gas_usd,
            "missed_gas_eth": missed_gas_eth,
            "missed_gas_usd": missed_gas_usd,
        }

    # Build global summary
    total_net_profit_after_included = total_profit_usd - total_included_gas_usd
    ratio = (total_net_profit_after_included / total_missed_gas_usd) if total_missed_gas_usd > 0 else None

    serializable["_summary"] = {
        "pairs_total": pairs_total,
        "pairs_executed": pairs_executed,
        "candidate_tx_total": candidate_tx_total,
        "executed_tx_total": executed_tx_total,
        "total_profit_usd": total_profit_usd,
        "total_included_gas_usd": total_included_gas_usd,
        "total_missed_gas_usd": total_missed_gas_usd,
        "total_net_profit_after_included_gas_usd": total_net_profit_after_included,
        "realized_to_missed_ratio": ratio,
    }

    # Pretty CLI summary
    print("\n=== MEV Summary ===")
    print(f"Pairs executed / total: {pairs_executed} / {pairs_total}")
    print(f"Executed tx / candidate tx: {executed_tx_total} / {candidate_tx_total}")
    print(f"Total profit (USD): {total_profit_usd:,.2f}")
    print(f"Included gas (USD): {total_included_gas_usd:,.2f}")
    print(f"Net profit after included gas (USD): {total_net_profit_after_included:,.2f}")
    print(f"Missed gas (USD): {total_missed_gas_usd:,.2f}")
    if ratio is not None:
        print(f"Realized-to-missed ratio: {ratio:,.2f}")
    else:
        print("Realized-to-missed ratio: N/A (no missed gas)")

    # Top 5 pairs by missed gas (USD)
    top = sorted(
        ((k, v) for k, v in serializable.items() if k != "_summary"),
        key=lambda kv: kv[1].get("missed_gas_usd", 0.0),
        reverse=True
    )[:5]
    if top:
        print("\nTop 5 pairs by missed gas (USD):")
        for k, v in top:
            print(f"  {k}: {v.get('missed_gas_usd', 0.0):,.2f} (decision: {v.get('decision')})")

    with open("mev_results.json", "w") as f:
        json.dump(serializable, f, indent=2)

    print(f"MEV optimization complete -> {len(serializable)} results saved to mev_results.json")
