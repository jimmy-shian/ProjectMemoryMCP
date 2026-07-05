"""File scanner for discovering and indexing source files."""

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from project_memory_mcp.static_analysis.language_registry import (
    get_registry,
    get_supported_extensions,
)


@dataclass
class FileInfo:
    """Information about a scanned file."""
    path: str
    relative_path: str
    filename: str
    extension: str
    language: str | None
    size_bytes: int
    hash: str
    last_modified: float
    is_source: bool
    is_test: bool
    is_config: bool
    is_entrypoint: bool


class FileScanner:
    """
    Scans a project directory for source files and extracts basic metadata.

    Features:
    - Multi-language support via tree-sitter
    - Configurable exclude patterns
    - SHA256 hash for change detection
    - File type classification (source, test, config, entrypoint)
    """

    DEFAULT_EXCLUDE_PATTERNS = {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        ".env",
        "build",
        "dist",
        "target",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".coverage",
        "htmlcov",
        "*.egg-info",
        ".tox",
        ".idea",
        ".vscode",
        # Archive/staging directories — should not be analyzed as active source.
        "_archive",
        ".archive",
        # MCP's own memory directory (contains the database/manual artifacts).
        ".project-memory",
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
        "*.pyc",
        "*.pyo",
        ".DS_Store",
        "Thumbs.db",
        "*.log",
        "*.tmp",
        "*.temp",
        "*.swp",
        "*.swo",
        "*~",
    }

    DEFAULT_TEST_PATTERNS = {
        "test_*.py",
        "*_test.py",
        "tests/**/*.py",
        "test/**/*.py",
        "spec/**/*.js",
        "spec/**/*.ts",
        "*_spec.rb",
        "*_test.go",
        "*Test.java",
        "test_*.rs",
        "*_test.cc",
        "*_test.cpp",
    }

    DEFAULT_CONFIG_PATTERNS = {
        "*.yaml",
        "*.yml",
        "*.json",
        "*.toml",
        "*.ini",
        "*.cfg",
        "*.conf",
        "*.config",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "requirements*.txt",
        "Pipfile",
        "Pipfile.lock",
        "poetry.lock",
        "Cargo.toml",
        "Cargo.lock",
        "go.mod",
        "go.sum",
        "pom.xml",
        "build.gradle",
        "package.json",
        "package-lock.json",
        "yarn.lock",
        "tsconfig.json",
        ".eslintrc*",
        ".prettierrc*",
        "Dockerfile",
        "docker-compose*.yml",
        "Makefile",
        "CMakeLists.txt",
    }

    DEFAULT_ENTRYPOINT_PATTERNS = {
        "main.py",
        "__main__.py",
        "app.py",
        "server.py",
        "cli.py",
        "run.py",
        "manage.py",
        "index.js",
        "index.ts",
        "main.js",
        "main.ts",
        "app.js",
        "app.ts",
        "server.js",
        "server.ts",
        "main.rs",
        "main.go",
        "Main.java",
        "Program.cs",
    }

    def __init__(
        self,
        project_root: str,
        exclude_patterns: set[str] | None = None,
        include_patterns: set[str] | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.exclude_patterns = exclude_patterns or self.DEFAULT_EXCLUDE_PATTERNS.copy()
        self.include_patterns = include_patterns or set()
        self.registry = get_registry()

    def scan(self) -> list[FileInfo]:
        """
        Scan the project directory for files.

        Returns:
            List of FileInfo objects for each discovered file
        """
        files = []
        supported_extensions = get_supported_extensions()

        for file_path in self._walk_files():
            try:
                file_info = self._analyze_file(file_path, supported_extensions)
                if file_info:
                    files.append(file_info)
            except Exception as e:
                # Log error but continue scanning
                print(f"Warning: Failed to analyze {file_path}: {e}")
                continue

        return files

    def _walk_files(self) -> list[Path]:
        """Walk the project directory and return all file paths."""
        paths = []

        for root, dirs, filenames in os.walk(self.project_root):
            # Filter out excluded directories
            dirs[:] = [d for d in dirs if not self._is_excluded(d, is_dir=True)]

            for filename in filenames:
                if self._is_excluded(filename, is_dir=False):
                    continue

                file_path = Path(root) / filename
                paths.append(file_path)

        return paths

    def _is_excluded(self, name: str, is_dir: bool = False) -> bool:
        """Check if a file/directory name matches exclude patterns."""
        for pattern in self.exclude_patterns:
            if self._match_pattern(name, pattern):
                return True
        return False

    def _match_pattern(self, name: str, pattern: str) -> bool:
        """Match a name against a glob pattern."""
        import fnmatch
        return fnmatch.fnmatch(name, pattern)

    def _analyze_file(self, file_path: Path, supported_extensions: set[str]) -> FileInfo | None:
        """Analyze a single file and return FileInfo."""
        # Check if extension is supported
        ext = file_path.suffix.lower()
        if ext not in supported_extensions and not self._is_special_file(file_path):
            return None

        # Get relative path
        try:
            relative_path = file_path.relative_to(self.project_root)
        except ValueError:
            relative_path = file_path

        # Get file stats
        stat = file_path.stat()
        size_bytes = stat.st_size
        last_modified = stat.st_mtime

        # Calculate hash
        file_hash = self._calculate_hash(file_path)

        # Determine language
        language = self.registry.get_language_for_file(str(file_path))

        # Classify file type
        is_source = language is not None
        is_test = self._is_test_file(relative_path)
        is_config = self._is_config_file(relative_path)
        is_entrypoint = self._is_entrypoint_file(relative_path)

        return FileInfo(
            path=str(file_path),
            relative_path=str(relative_path),
            filename=file_path.name,
            extension=ext,
            language=language,
            size_bytes=size_bytes,
            hash=file_hash,
            last_modified=last_modified,
            is_source=is_source,
            is_test=is_test,
            is_config=is_config,
            is_entrypoint=is_entrypoint,
        )

    def _is_special_file(self, file_path: Path) -> bool:
        """Check if file is a special file we should include even without language support."""
        name = file_path.name
        for pattern in self.DEFAULT_CONFIG_PATTERNS:
            import fnmatch
            if fnmatch.fnmatch(name, pattern):
                return True
        return False

    def _is_test_file(self, relative_path: Path) -> bool:
        """Check if file matches test patterns."""
        path_str = str(relative_path)
        name = relative_path.name

        for pattern in self.DEFAULT_TEST_PATTERNS:
            import fnmatch
            if fnmatch.fnmatch(path_str, pattern) or fnmatch.fnmatch(name, pattern):
                return True

        # Check if in test directory
        parts = relative_path.parts
        if any(p in {"test", "tests", "testing", "spec", "specs"} for p in parts):
            return True

        return False

    def _is_config_file(self, relative_path: Path) -> bool:
        """Check if file matches config patterns."""
        name = relative_path.name

        for pattern in self.DEFAULT_CONFIG_PATTERNS:
            import fnmatch
            if fnmatch.fnmatch(name, pattern):
                return True

        return False

    def _is_entrypoint_file(self, relative_path: Path) -> bool:
        """Check if file matches entrypoint patterns."""
        name = relative_path.name

        if name in self.DEFAULT_ENTRYPOINT_PATTERNS:
            return True

        # Check for common entrypoint patterns
        entrypoint_names = {
            "main", "app", "server", "cli", "run", "manage",
            "index", "start", "bootstrap", "entry", "launcher",
        }
        stem = relative_path.stem.lower()
        if stem in entrypoint_names:
            return True

        return False

    def _calculate_hash(self, file_path: Path) -> str:
        """Calculate SHA256 hash of file contents."""
        hasher = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                # Read in chunks to handle large files
                for chunk in iter(lambda: f.read(8192), b""):
                    hasher.update(chunk)
        except Exception:
            # If we can't read the file, return empty hash
            return ""
        return hasher.hexdigest()

    def get_file_info(self, file_path: str) -> FileInfo | None:
        """Get FileInfo for a specific file."""
        path = Path(file_path)
        if not path.exists():
            return None

        supported_extensions = get_supported_extensions()
        return self._analyze_file(path, supported_extensions)

    def detect_changed_files(
        self,
        previous_files: dict[str, str],
    ) -> list[FileInfo]:
        """
        Detect files that have changed since last scan.

        Args:
            previous_files: Dict mapping relative_path -> hash

        Returns:
            List of FileInfo for changed or new files
        """
        current_files = {f.relative_path: f.hash for f in self.scan()}

        changed = []
        for rel_path, new_hash in current_files.items():
            old_hash = previous_files.get(rel_path)
            if old_hash != new_hash:
                # File is new or changed
                file_info = next(f for f in self.scan() if f.relative_path == rel_path)
                changed.append(file_info)

        return changed
