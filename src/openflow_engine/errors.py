class CycleError(ValueError):
    """Raised when a pipeline graph is not acyclic."""


class InvalidExpressionError(ValueError):
    """Raised when a filter expression contains unsupported syntax."""


class PipelineExecutionError(RuntimeError):
    """Raised when a pipeline node fails during execution."""

    def __init__(self, message: str, logs: list[object] | None = None) -> None:
        super().__init__(message)
        self.logs = logs or []


class SecurityError(PermissionError):
    """Raised when a security validation or access constraint fails."""


class ConnectorError(RuntimeError):
    """Raised when a database or storage connector fails to connect or execute."""
