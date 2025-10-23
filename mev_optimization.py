from transaction import Transaction

# Computes the profit
def helper(src, dst, q, r, exo):
    return q * (exo[src] - exo[dst] * r)

# Argmax function of max cumulative profit
def cumulative_argmax(values):
    running, best_val, best_idx = 0, float('-inf'), -1
    for i, v in enumerate(values):
        running += v
        if running > best_val:
            best_val, best_idx = running, i
    return best_idx, best_val

# Computes transaction to profit off of target asset.
# Implementation of algorithm presented in paper
def compute_batch(batch, exo, base_asset="A"):
    assets = sorted({tx.src for tx in batch} | {tx.dst for tx in batch})
    results = {}

    for j in [a for a in assets if a != base_asset]:
        print(f"Pair ({base_asset}, {j})")
        # Forward direction tau_1 -> tau_j
        fwd = [tx for tx in batch if tx.src == base_asset and tx.dst == j]
        fwd.sort(key=lambda x: x.r)
        fwd_profits = [helper(tx.src, tx.dst, tx.q, tx.r, exo) for tx in fwd]
        k1, profit1 = cumulative_argmax(fwd_profits)

        # Reverse direction tau_j -> tau_1
        rev = [tx for tx in batch if tx.src == j and tx.dst == base_asset]
        rev.sort(key=lambda x: x.r)
        rev_profits = [helper(tx.src, tx.dst, tx.q, tx.r, exo) for tx in rev]
        k2, profit2 = cumulative_argmax(rev_profits)

        if profit1 <= 0 and profit2 <= 0:
            decision = "Do nothing"
            executed = []
            total = 0.0

        elif profit1 >= profit2:
            decision = f"Execute {base_asset}->{j} and mediator ({j}->{base_asset})"
            executed = fwd[: k1 + 1]
            total = profit1

            # Insert mediator batch
            total_qty = sum(tx.q for tx in executed)
            avg_rate = sum(tx.r * tx.q for tx in executed) / max(total_qty, 1e-12)
            mediator = Transaction(j, base_asset, total_qty, 1 / avg_rate)
            executed.append(mediator)

        else:
            decision = f"Execute {j}->{base_asset} and mediator ({base_asset}->{j})"
            executed = rev[: k2 + 1]
            total = profit2

            # Insert mediator batch
            total_qty = sum(tx.q for tx in executed)
            avg_rate = sum(tx.r * tx.q for tx in executed) / max(total_qty, 1e-12)
            mediator = Transaction(base_asset, j, total_qty, 1 / avg_rate)
            executed.append(mediator)

        print(f"PROFIT1={profit1:.4f}, PROFIT2={profit2:.4f}")
        print(f"Decision: {decision}")
        print(f"Executed transactions: {executed}")
        print("")

        results[(base_asset, j)] = {
            "decision": decision,
            "profit": total,
            "executed": executed
        }

    return results


if __name__ == "__main__":
    # example test case presented in paper
    example_batch = [
        Transaction("A", "B", 2, 0.5),
        Transaction("B", "C", 1, 4),
        Transaction("C", "A", 4, 0.5)
    ]
    exo = {"A": 1.0, "B": 1.0, "C": 1.0}  # exogenous market prices
    result = compute_batch(example_batch,exo,"A")
    print(result)
