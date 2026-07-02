"""Language registry for multi-language support in static analysis."""

import os
from dataclasses import dataclass


@dataclass
class LanguageInfo:
    """Information about a supported programming language."""
    name: str
    extensions: list[str]
    tree_sitter_language: str  # tree-sitter grammar name
    tree_sitter_module: str    # Python package name for tree-sitter binding
    aliases: list[str]         # Alternative names
    file_patterns: list[str]   # Common filename patterns


class LanguageRegistry:
    """Registry of supported languages and their configurations."""

    def __init__(self):
        self._languages: dict[str, LanguageInfo] = {}
        self._extension_map: dict[str, str] = {}
        self._register_default_languages()

    def _register_default_languages(self) -> None:
        """Register all supported languages."""
        languages = [
            LanguageInfo(
                name="python",
                extensions=[".py", ".pyw", ".pyi"],
                tree_sitter_language="python",
                tree_sitter_module="tree_sitter_python",
                aliases=["python3", "py"],
                file_patterns=["*.py", "*.pyw", "*.pyi"],
            ),
            LanguageInfo(
                name="javascript",
                extensions=[".js", ".jsx", ".mjs", ".cjs"],
                tree_sitter_language="javascript",
                tree_sitter_module="tree_sitter_javascript",
                aliases=["js", "node"],
                file_patterns=["*.js", "*.jsx", "*.mjs", "*.cjs"],
            ),
            LanguageInfo(
                name="typescript",
                extensions=[".ts", ".tsx", ".mts", ".cts"],
                tree_sitter_language="typescript",
                tree_sitter_module="tree_sitter_typescript",
                aliases=["ts"],
                file_patterns=["*.ts", "*.tsx", "*.mts", "*.cts"],
            ),
            LanguageInfo(
                name="rust",
                extensions=[".rs"],
                tree_sitter_language="rust",
                tree_sitter_module="tree_sitter_rust",
                aliases=["rs"],
                file_patterns=["*.rs"],
            ),
            LanguageInfo(
                name="go",
                extensions=[".go"],
                tree_sitter_language="go",
                tree_sitter_module="tree_sitter_go",
                aliases=["golang"],
                file_patterns=["*.go"],
            ),
            LanguageInfo(
                name="java",
                extensions=[".java"],
                tree_sitter_language="java",
                tree_sitter_module="tree_sitter_java",
                aliases=[],
                file_patterns=["*.java"],
            ),
            LanguageInfo(
                name="c",
                extensions=[".c", ".h"],
                tree_sitter_language="c",
                tree_sitter_module="tree_sitter_c",
                aliases=[],
                file_patterns=["*.c", "*.h"],
            ),
            LanguageInfo(
                name="cpp",
                extensions=[".cpp", ".cc", ".cxx", ".c++", ".hpp", ".hh", ".hxx", ".h++"],
                tree_sitter_language="cpp",
                tree_sitter_module="tree_sitter_cpp",
                aliases=["c++", "cxx"],
                file_patterns=["*.cpp", "*.cc", "*.cxx", "*.hpp", "*.hh"],
            ),
            LanguageInfo(
                name="csharp",
                extensions=[".cs"],
                tree_sitter_language="c_sharp",
                tree_sitter_module="tree_sitter_c_sharp",
                aliases=["cs", "c#"],
                file_patterns=["*.cs"],
            ),
            LanguageInfo(
                name="ruby",
                extensions=[".rb", ".rbw"],
                tree_sitter_language="ruby",
                tree_sitter_module="tree_sitter_ruby",
                aliases=[],
                file_patterns=["*.rb", "*.rbw"],
            ),
            LanguageInfo(
                name="php",
                extensions=[".php", ".phtml", ".php3", ".php4", ".php5", ".phps"],
                tree_sitter_language="php",
                tree_sitter_module="tree_sitter_php",
                aliases=[],
                file_patterns=["*.php", "*.phtml"],
            ),
            LanguageInfo(
                name="swift",
                extensions=[".swift"],
                tree_sitter_language="swift",
                tree_sitter_module="tree_sitter_swift",
                aliases=[],
                file_patterns=["*.swift"],
            ),
            LanguageInfo(
                name="kotlin",
                extensions=[".kt", ".kts"],
                tree_sitter_language="kotlin",
                tree_sitter_module="tree_sitter_kotlin",
                aliases=[],
                file_patterns=["*.kt", "*.kts"],
            ),
            LanguageInfo(
                name="scala",
                extensions=[".scala", ".sc"],
                tree_sitter_language="scala",
                tree_sitter_module="tree_sitter_scala",
                aliases=[],
                file_patterns=["*.scala", "*.sc"],
            ),
            LanguageInfo(
                name="r",
                extensions=[".r", ".R"],
                tree_sitter_language="r",
                tree_sitter_module="tree_sitter_r",
                aliases=[],
                file_patterns=["*.r", "*.R"],
            ),
            LanguageInfo(
                name="lua",
                extensions=[".lua"],
                tree_sitter_language="lua",
                tree_sitter_module="tree_sitter_lua",
                aliases=[],
                file_patterns=["*.lua"],
            ),
            LanguageInfo(
                name="perl",
                extensions=[".pl", ".pm", ".pod", ".t"],
                tree_sitter_language="perl",
                tree_sitter_module="tree_sitter_perl",
                aliases=[],
                file_patterns=["*.pl", "*.pm", "*.pod", "*.t"],
            ),
            LanguageInfo(
                name="bash",
                extensions=[".sh", ".bash", ".zsh", ".fish"],
                tree_sitter_language="bash",
                tree_sitter_module="tree_sitter_bash",
                aliases=["shell"],
                file_patterns=["*.sh", "*.bash"],
            ),
            LanguageInfo(
                name="toml",
                extensions=[".toml"],
                tree_sitter_language="toml",
                tree_sitter_module="tree_sitter_toml",
                aliases=[],
                file_patterns=["*.toml"],
            ),
            LanguageInfo(
                name="json",
                extensions=[".json", ".jsonc"],
                tree_sitter_language="json",
                tree_sitter_module="tree_sitter_json",
                aliases=[],
                file_patterns=["*.json", "*.jsonc"],
            ),
            LanguageInfo(
                name="yaml",
                extensions=[".yaml", ".yml"],
                tree_sitter_language="yaml",
                tree_sitter_module="tree_sitter_yaml",
                aliases=[],
                file_patterns=["*.yaml", "*.yml"],
            ),
            LanguageInfo(
                name="html",
                extensions=[".html", ".htm", ".xhtml"],
                tree_sitter_language="html",
                tree_sitter_module="tree_sitter_html",
                aliases=[],
                file_patterns=["*.html", "*.htm", "*.xhtml"],
            ),
            LanguageInfo(
                name="css",
                extensions=[".css", ".scss", ".sass", ".less"],
                tree_sitter_language="css",
                tree_sitter_module="tree_sitter_css",
                aliases=[],
                file_patterns=["*.css", "*.scss", "*.sass", "*.less"],
            ),
            LanguageInfo(
                name="sql",
                extensions=[".sql"],
                tree_sitter_language="sql",
                tree_sitter_module="tree_sitter_sql",
                aliases=[],
                file_patterns=["*.sql"],
            ),
            LanguageInfo(
                name="markdown",
                extensions=[".md", ".markdown", ".mdown", ".mkd"],
                tree_sitter_language="markdown",
                tree_sitter_module="tree_sitter_markdown",
                aliases=[],
                file_patterns=["*.md", "*.markdown", "*.mdown", "*.mkd"],
            ),
            LanguageInfo(
                name="dockerfile",
                extensions=[],
                tree_sitter_language="dockerfile",
                tree_sitter_module="tree_sitter_dockerfile",
                aliases=[],
                file_patterns=["Dockerfile", "dockerfile", "Dockerfile.*"],
            ),
            LanguageInfo(
                name="make",
                extensions=[],
                tree_sitter_language="make",
                tree_sitter_module="tree_sitter_make",
                aliases=[],
                file_patterns=["Makefile", "makefile", "GNUmakefile", "*.mk"],
            ),
            LanguageInfo(
                name="cmake",
                extensions=[".cmake"],
                tree_sitter_language="cmake",
                tree_sitter_module="tree_sitter_cmake",
                aliases=[],
                file_patterns=["CMakeLists.txt", "*.cmake"],
            ),
            LanguageInfo(
                name="protobuf",
                extensions=[".proto"],
                tree_sitter_language="protobuf",
                tree_sitter_module="tree_sitter_protobuf",
                aliases=[],
                file_patterns=["*.proto"],
            ),
            LanguageInfo(
                name="graphql",
                extensions=[".graphql", ".gql"],
                tree_sitter_language="graphql",
                tree_sitter_module="tree_sitter_graphql",
                aliases=[],
                file_patterns=["*.graphql", "*.gql"],
            ),
            LanguageInfo(
                name="vue",
                extensions=[".vue"],
                tree_sitter_language="vue",
                tree_sitter_module="tree_sitter_vue",
                aliases=[],
                file_patterns=["*.vue"],
            ),
            LanguageInfo(
                name="svelte",
                extensions=[".svelte"],
                tree_sitter_language="svelte",
                tree_sitter_module="tree_sitter_svelte",
                aliases=[],
                file_patterns=["*.svelte"],
            ),
            LanguageInfo(
                name="matlab",
                extensions=[".m"],
                tree_sitter_language="matlab",
                tree_sitter_module="tree_sitter_matlab",
                aliases=[],
                file_patterns=["*.m"],
            ),
            LanguageInfo(
                name="julia",
                extensions=[".jl"],
                tree_sitter_language="julia",
                tree_sitter_module="tree_sitter_julia",
                aliases=[],
                file_patterns=["*.jl"],
            ),
            LanguageInfo(
                name="rst",
                extensions=[".rst"],
                tree_sitter_language="rst",
                tree_sitter_module="tree_sitter_rst",
                aliases=[],
                file_patterns=["*.rst"],
            ),
        ]

        for lang in languages:
            self.register(lang)

    def register(self, language: LanguageInfo) -> None:
        """Register a language."""
        self._languages[language.name] = language
        for ext in language.extensions:
            self._extension_map[ext.lower()] = language.name
        for alias in language.aliases:
            self._extension_map[alias.lower()] = language.name

    def get_language(self, name: str) -> LanguageInfo | None:
        """Get language info by name or alias."""
        return self._languages.get(name.lower())

    def get_language_for_file(self, file_path: str) -> str | None:
        """Get language name for a file path."""
        # First check by extension
        ext = os.path.splitext(file_path)[1].lower()
        if ext in self._extension_map:
            return self._extension_map[ext]

        # Check by filename patterns (for extensionless files like Makefile, Dockerfile)
        filename = os.path.basename(file_path)
        for lang in self._languages.values():
            for pattern in lang.file_patterns:
                import fnmatch
                if fnmatch.fnmatch(filename, pattern):
                    return lang.name

        return None

    def get_language_for_extension(self, extension: str) -> str | None:
        """Get language name for a file extension."""
        return self._extension_map.get(extension.lower())

    def get_all_languages(self) -> list[LanguageInfo]:
        """Get all registered languages."""
        return list(self._languages.values())

    def get_supported_extensions(self) -> set[str]:
        """Get all supported file extensions."""
        return set(self._extension_map.keys())

    def is_supported(self, file_path: str) -> bool:
        """Check if a file is supported."""
        return self.get_language_for_file(file_path) is not None


# Global registry instance
_registry: LanguageRegistry | None = None


def get_registry() -> LanguageRegistry:
    """Get the global language registry instance."""
    global _registry
    if _registry is None:
        _registry = LanguageRegistry()
    return _registry


def get_supported_extensions() -> set[str]:
    """Get all supported file extensions."""
    return get_registry().get_supported_extensions()


def get_language_for_file(file_path: str) -> str | None:
    """Get language name for a file path."""
    return get_registry().get_language_for_file(file_path)
