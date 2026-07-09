"""Configuration management for Project Memory MCP."""

import json
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Project settings loaded from environment variables, .env file, and config file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Project
    project_root: str = Field(default=".", description="Project root directory")
    memory_dir: str = Field(default=".project-memory", description="Memory directory name")

    # Database
    db_path: str = Field(default=".project-memory/project_knowledge.db", description="SQLite database path")
    db_echo: bool = Field(default=False, description="Echo SQL queries")

    # Transport
    transport: str = Field(default="stdio", description="Transport mode: stdio or http")

    # LLM Configuration
    llm_mode: str = Field(default="server_driven", description="LLM mode: agent_driven or server_driven")
    llm_provider: str = Field(default="myself", description="LLM provider: anthropic, openai, google, myself")
    llm_api_key: str = Field(default="not-needed", description="LLM API key")
    llm_model: str = Field(default="patcher-main", description="LLM model name")
    llm_api_base: str = Field(default="http://localhost:4000/v1", description="LLM API base URL (for custom endpoints)")
    llm_temperature: float = Field(default=0.1, description="LLM temperature")

    # Analysis
    use_vector_similarity: bool = Field(default=False, description="Use vector similarity search")
    max_analysis_depth: int = Field(default=3, description="Maximum graph traversal depth")

    # Safety
    require_impact_analysis_before_edit: bool = Field(default=True, description="Require impact analysis before edit")
    require_confirmation_before_delete: bool = Field(default=True, description="Require confirmation before delete")
    preserve_comments: bool = Field(default=True, description="Preserve comments during edits")
    preserve_commented_code: bool = Field(default=True, description="Preserve commented-out code")

    # Exclude patterns
    exclude_patterns: list[str] = Field(
        default=[
            ".git",
            "node_modules",
            "__pycache__",
            ".venv",
            "venv",
            "env",
            "build",
            "dist",
            "target",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "*.egg-info",
            ".tox",
            ".idea",
            ".vscode",
            "*.pyc",
            "*.pyo",
            "*.pyd",
            "*.so",
            "*.dll",
            "*.exe",
            "*.bin",
            "*.obj",
            "*.o",
            "*.a",
            "*.lib",
            "*.jar",
            "*.war",
            "*.ear",
            "*.class",
            ".DS_Store",
            "Thumbs.db",
            "*.log",
            "*.tmp",
            "*.temp",
            "*.swp",
            "*.swo",
            "*~",
        ],
        description="File/directory patterns to exclude",
    )

    # Supported languages
    languages: list[str] = Field(
        default=["python", "typescript", "javascript", "rust", "go", "java", "c", "cpp"],
        description="Languages to analyze",
    )

    # Workflow configuration
    workflow_auto_index: bool = Field(default=True, description="Automatically run indexing")
    workflow_auto_build_graph: bool = Field(default=True, description="Automatically build knowledge graph")
    workflow_auto_generate_manual: bool = Field(default=True, description="Automatically generate manual")

    # Parallel analysis configuration
    parallel_max_workers: int = Field(default=4, description="Max worker threads for parallel static analysis")
    parallel_max_llm_concurrent: int = Field(default=2, description="Max concurrent LLM calls")
    parallel_batch_size: int = Field(default=10, description="Batch size for parallel processing")
    parallel_enable_static: bool = Field(default=True, description="Enable parallel static analysis")
    parallel_enable_llm: bool = Field(default=True, description="Enable parallel LLM analysis")

    @property
    def db_full_path(self) -> str:
        """Get full database path."""
        root = Path(self.project_root).resolve()
        return str(root / self.db_path)

    @classmethod
    def from_file(cls, config_path: str | Path) -> "Settings":
        """Load settings from a YAML or JSON configuration file."""
        path = Path(config_path).resolve()
        
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")
        
        with open(path, "r", encoding="utf-8") as f:
            if path.suffix in (".yaml", ".yml"):
                config_data = yaml.safe_load(f)
            elif path.suffix == ".json":
                config_data = json.load(f)
            else:
                raise ValueError(f"Unsupported config file format: {path.suffix}. Use .yaml, .yml, or .json")
        
        if config_data is None:
            config_data = {}
        
        # Handle environment variable substitution
        config_data = cls._substitute_env_vars(config_data)
        config_data = cls.flatten_config(config_data)
        
        return cls(**config_data)
    
    @classmethod
    def _substitute_env_vars(cls, data: Any) -> Any:
        """Recursively substitute environment variables in config values."""
        if isinstance(data, dict):
            return {k: cls._substitute_env_vars(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [cls._substitute_env_vars(item) for item in data]
        elif isinstance(data, str) and data.startswith("${") and data.endswith("}"):
            env_var = data[2:-1]
            return os.environ.get(env_var, data)
        else:
            return data

    @classmethod
    def flatten_config(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Flatten documented YAML/JSON sections into Settings field names.

        The public examples use grouped sections such as ``llm.mode`` and
        ``database.path``. Internally the settings object uses flat env-friendly
        field names, so this adapter keeps both formats working.
        """
        flattened: dict[str, Any] = {
            k: v for k, v in data.items() if not isinstance(v, dict)
        }

        project = data.get("project", {})
        if isinstance(project, dict):
            if "root" in project:
                flattened["project_root"] = project["root"]
            if "memory_dir" in project:
                flattened["memory_dir"] = project["memory_dir"]

        database = data.get("database", {})
        if isinstance(database, dict):
            if "path" in database:
                flattened["db_path"] = database["path"]
            if "echo" in database:
                flattened["db_echo"] = database["echo"]

        llm = data.get("llm", {})
        if isinstance(llm, dict):
            for key in ("mode", "provider", "api_key", "model", "api_base", "temperature"):
                if key in llm:
                    flattened[f"llm_{key}"] = llm[key]

        analysis = data.get("analysis", {})
        if isinstance(analysis, dict):
            flattened.update(analysis)

        safety = data.get("safety", {})
        if isinstance(safety, dict):
            flattened.update(safety)

        workflow = data.get("workflow", {})
        if isinstance(workflow, dict):
            if "auto_index" in workflow:
                flattened["workflow_auto_index"] = workflow["auto_index"]
            if "auto_build_graph" in workflow:
                flattened["workflow_auto_build_graph"] = workflow["auto_build_graph"]
            if "auto_generate_manual" in workflow:
                flattened["workflow_auto_generate_manual"] = workflow["auto_generate_manual"]

        parallel = data.get("parallel", {})
        if isinstance(parallel, dict):
            if "max_workers" in parallel:
                flattened["parallel_max_workers"] = parallel["max_workers"]
            if "max_llm_concurrent" in parallel:
                flattened["parallel_max_llm_concurrent"] = parallel["max_llm_concurrent"]
            if "batch_size" in parallel:
                flattened["parallel_batch_size"] = parallel["batch_size"]
            if "enable_static" in parallel:
                flattened["parallel_enable_static"] = parallel["enable_static"]
            if "enable_llm" in parallel:
                flattened["parallel_enable_llm"] = parallel["enable_llm"]

        for key in ("exclude_patterns", "languages", "transport"):
            if key in data:
                flattened[key] = data[key]

        return flattened
    
    def to_dict(self) -> dict[str, Any]:
        """Convert settings to dictionary for workflow config."""
        return self.model_dump()


# Global settings instance
_settings: Settings | None = None


def get_settings(config_path: str | Path | None = None) -> Settings:
    """Get the global settings instance, optionally loading from config file."""
    global _settings
    if _settings is None:
        if config_path:
            _settings = Settings.from_file(config_path)
        else:
            _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Reset the global settings (for testing)."""
    global _settings
    _settings = None


def load_config(config_path: str | Path) -> dict[str, Any]:
    """Load configuration from file and return as dictionary."""
    path = Path(config_path).resolve()
    
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    
    with open(path, "r", encoding="utf-8") as f:
        if path.suffix in (".yaml", ".yml"):
            config_data = yaml.safe_load(f)
        elif path.suffix == ".json":
            config_data = json.load(f)
        else:
            raise ValueError(f"Unsupported config file format: {path.suffix}. Use .yaml, .yml, or .json")
    
    if config_data is None:
        config_data = {}
    
    # Handle environment variable substitution
    config_data = Settings._substitute_env_vars(config_data)
    config_data = Settings.flatten_config(config_data)
    
    return config_data
