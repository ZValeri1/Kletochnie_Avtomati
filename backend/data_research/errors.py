class DataResearchError(ValueError):
    code = "DATA_RESEARCH_ERROR"


class ProjectDataError(DataResearchError):
    code = "CORRUPTED_PROJECT"


class ProjectConflictError(DataResearchError):
    code = "PROJECT_EXISTS"


class ProjectNotFoundError(ProjectDataError):
    code = "PROJECT_NOT_FOUND"


class ProjectConfirmationError(DataResearchError):
    code = "CONFIRMATION_REQUIRED"


class UnsupportedProjectSchemaError(ProjectDataError):
    code = "UNSUPPORTED_SCHEMA"


class StorageUnavailableError(DataResearchError):
    code = "STORAGE_UNAVAILABLE"
