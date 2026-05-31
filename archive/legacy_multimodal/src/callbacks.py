class EarlyStopping:
    def __init__(self, patience: int = 2, mode: str = 'max'):
        self.patience = patience
        self.mode = mode
        self.best = None
        self.bad_epochs = 0

    def step(self, value: float) -> bool:
        if self.best is None:
            self.best = value
            return False

        improved = value > self.best if self.mode == 'max' else value < self.best
        if improved:
            self.best = value
            self.bad_epochs = 0
            return False

        self.bad_epochs += 1
        return self.bad_epochs >= self.patience
