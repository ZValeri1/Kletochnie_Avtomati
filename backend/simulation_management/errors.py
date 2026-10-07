class SimulationManagementError(RuntimeError):
    code = "SIMULATION_ERROR"


class RevisionConflictError(SimulationManagementError):
    code = "REVISION_CONFLICT"


class InvalidSimulationCommandError(SimulationManagementError):
    code = "INVALID_SIMULATION_COMMAND"


class SimulationNotFoundError(InvalidSimulationCommandError):
    code = "SIMULATION_NOT_FOUND"


class PreparationCommandError(InvalidSimulationCommandError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class SimulationTimeoutError(SimulationManagementError):
    code = "SIMULATION_TIMEOUT"
