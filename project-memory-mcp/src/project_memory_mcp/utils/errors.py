"""Error utilities for Project Memory MCP."""

from typing import Any


class ProjectMemoryError(Exception):
    """Base exception for Project Memory MCP."""

    def __init__(self, message: str, code: str = "UNKNOWN_ERROR", details: dict[str, Any] | None = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(message)


class NotFoundError(ProjectMemoryError):
    """Entity not found in database."""
    def __init__(self, entity_type: str, identifier: str):
        super().__init__(
            f"{entity_type} not found: {identifier}",
            code="NOT_FOUND",
            details={"entity_type": entity_type, "identifier": identifier}
        )


class ValidationError(ProjectMemoryError):
    """Input validation failed."""
    def __init__(self, message: str, field: str | None = None):
        super().__init__(
            message,
            code="VALIDATION_ERROR",
            details={"field": field} if field else {}
        )


class AnalysisError(ProjectMemoryError):
    """LLM analysis failed."""
    def __init__(self, message: str, task_id: str | None = None):
        super().__init__(
            message,
            code="ANALYSIS_ERROR",
            details={"task_id": task_id} if task_id else {}
        )


class DatabaseError(ProjectMemoryError):
    """Database operation failed."""
    def __init__(self, message: str, operation: str | None = None):
        super().__init__(
            message,
            code="DATABASE_ERROR",
            details={"operation": operation} if operation else {}
        )


class ConfigurationError(ProjectMemoryError):
    """Configuration error."""
    def __init__(self, message: str, config_key: str | None = None):
        super().__init__(
            message,
            code="CONFIGURATION_ERROR",
            details={"config_key": config_key} if config_key else {}
        )


class LLMError(ProjectMemoryError):
    """LLM API error."""
    def __init__(self, message: str, provider: str | None = None, model: str | None = None):
        super().__init__(
            message,
            code="LLM_ERROR",
            details={"provider": provider, "model": model}
        )


class ToolError(ProjectMemoryError):
    """MCP tool execution error."""
    def __init__(self, message: str, tool_name: str | None = None):
        super().__init__(
            message,
            code="TOOL_ERROR",
            details={"tool_name": tool_name} if tool_name else {}
        )
