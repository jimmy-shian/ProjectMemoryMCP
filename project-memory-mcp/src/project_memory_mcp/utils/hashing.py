"""Utility functions for Project Memory MCP."""

import hashlib
from pathlib import Path


def calculate_file_hash(
    file_path: str | Path,
    content: bytes | None = None,
) -> str:
    """
    Calculate SHA256 hash of a file.

    Args:
        file_path: Path to the file
        content: Optional pre-read content (bytes)

    Returns:
        SHA256 hash as hex string
    """
    hasher = hashlib.sha256()

    if content is not None:
        hasher.update(content)
    else:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)

    return hasher.hexdigest()


def get_file_extension(file_path: str | Path) -> str:
    """Get file extension including the dot."""
    return Path(file_path).suffix.lower()


def is_test_file(file_path: str | Path) -> bool:
    """Check if a file is a test file based on naming patterns."""
    path = Path(file_path)
    name = path.name.lower()
    parts = path.parts

    test_indicators = [
        "test_",
        "_test.",
        "_spec.",
        "tests/",
        "test/",
        "spec/",
        "__tests__/",
    ]

    for indicator in test_indicators:
        if indicator in name or indicator in "/".join(parts).lower():
            return True

    return False


def is_config_file(file_path: str | Path) -> bool:
    """Check if a file is a configuration file."""
    path = Path(file_path)
    name = path.name.lower()

    config_patterns = [
        ".toml",
        ".yaml",
        ".yml",
        ".json",
        ".ini",
        ".cfg",
        ".conf",
        "dockerfile",
        "makefile",
        "requirements",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "package.json",
        "tsconfig.json",
        "cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
    ]

    return any(pattern in name for pattern in config_patterns)


def is_entrypoint_file(file_path: str | Path) -> bool:
    """Check if a file is likely an entry point."""
    path = Path(file_path)
    name = path.stem.lower()

    entrypoint_names = {
        "main", "app", "server", "cli", "run", "manage",
        "index", "start", "bootstrap", "entry", "launcher",
    }

    return name in entrypoint_names


def sanitize_path(file_path: str, project_root: str) -> str:
    """Sanitize a file path relative to project root."""
    try:
        path = Path(file_path).resolve()
        root = Path(project_root).resolve()
        return str(path.relative_to(root))
    except Exception:
        return file_path


def truncate_string(s: str, max_length: int = 200) -> str:
    """Truncate a string to max length with ellipsis."""
    if len(s) <= max_length:
        return s
    return s[:max_length - 3] + "..."


def parse_json_safe(s: str, default=None):
    """Safely parse JSON string."""
    import json
    try:
        return json.loads(s)
    except Exception:
        return default


def to_json_safe(obj) -> str:
    """Safely convert object to JSON string."""
    import json
    try:
        return json.dumps(obj, default=str, ensure_ascii=False)
    except Exception:
        return "{}"
