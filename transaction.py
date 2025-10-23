class Transaction:
    def __init__(self, source_token, dest_token, quantity, rate):
        self.src = source_token
        self.dst = dest_token
        self.q = quantity
        self.r = rate

    def __repr__(self):
        return f"{self.src}->{self.dst} q={self.q} r={self.r}"
