class AtomicModelError(ValueError):
    pass


class TopologyError(AtomicModelError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class InitializationError(AtomicModelError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class StateInvariantError(AtomicModelError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class InvalidEventError(AtomicModelError):
    pass
