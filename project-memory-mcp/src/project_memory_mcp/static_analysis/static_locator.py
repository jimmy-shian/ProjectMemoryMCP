"""Static code locator - extracts code entities from source files using tree-sitter."""

from dataclasses import dataclass, field
from typing import Any, Optional

from tree_sitter import Language, Parser, Query, QueryCursor, Tree

from project_memory_mcp.static_analysis.ast_queries import get_all_queries_for_language, get_query
from project_memory_mcp.static_analysis.language_registry import get_language_for_file, get_registry


@dataclass
class CodeEntity:
    """Represents a code entity (function, class, variable, etc.)."""
    entity_type: str           # function, class, variable, import, call, etc.
    name: str
    qualified_name: str | None = None
    start_line: int = 0
    end_line: int = 0
    start_byte: int = 0
    end_byte: int = 0
    source_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    parent_entity: Optional["CodeEntity"] = None
    children: list["CodeEntity"] = field(default_factory=list)


@dataclass
class FileAnalysis:
    """Results of analyzing a single file."""
    file_path: str
    language: str
    entities: list[CodeEntity] = field(default_factory=list)
    imports: list[CodeEntity] = field(default_factory=list)
    functions: list[CodeEntity] = field(default_factory=list)
    classes: list[CodeEntity] = field(default_factory=list)
    variables: list[CodeEntity] = field(default_factory=list)
    calls: list[CodeEntity] = field(default_factory=list)
    comments: list[CodeEntity] = field(default_factory=list)
    docstrings: list[CodeEntity] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class StaticLocator:
    """
    Extracts code entities from source files using tree-sitter AST parsing.

    Supports multiple languages and provides structured access to:
    - Functions and their names (functions, classes, variables)
    - Imports/dependencies
    - Function/method calls
    - Comments and docstrings
    """

    def __init__(self):
        self.registry = get_registry()
        self._parsers: dict[str, Parser] = {}
        self._queries: dict[str, dict[str, Query]] = {}

    def _get_parser(self, language: str) -> Parser | None:
        """Get or create a parser for the given language."""
        if language in self._parsers:
            return self._parsers[language]

        lang_info = self.registry.get_language(language)
        if not lang_info:
            return None

        try:
            # Import the tree-sitter module dynamically
            module = __import__(lang_info.tree_sitter_module)
            ts_language = Language(module.language())
            parser = Parser()
            parser.language = ts_language
            self._parsers[language] = parser
            return parser
        except Exception as e:
            print(f"Failed to create parser for {language}: {e}")
            return None

    def _get_queries(self, language: str) -> dict[str, Query]:
        """Get or create queries for the given language."""
        if language in self._queries:
            return self._queries[language]

        lang_info = self.registry.get_language(language)
        if not lang_info:
            return {}

        try:
            module = __import__(lang_info.tree_sitter_module)
            ts_language = Language(module.language())

            queries = {}
            available_queries = get_all_queries_for_language(language)

            for query_type in available_queries:
                query_str = get_query(language, query_type)
                if query_str:
                    queries[query_type] = Query(ts_language, query_str)

            self._queries[language] = queries
            return queries
        except Exception as e:
            print(f"Failed to create queries for {language}: {e}")
            return {}

    def analyze_file(self, file_path: str) -> FileAnalysis:
        """
        Analyze a source file and extract all code entities.

        Args:
            file_path: Path to the source file

        Returns:
            FileAnalysis with all extracted entities
        """
        # Read file content
        try:
            with open(file_path, encoding="utf-8") as f:
                source_code = f.read()
        except UnicodeDecodeError:
            # Try reading as binary for non-UTF8 files
            with open(file_path, "rb") as f:
                source_bytes = f.read()
            source_code = source_bytes.decode("utf-8", errors="replace")

        # Determine language
        language = get_language_for_file(file_path)
        if not language:
            return FileAnalysis(
                file_path=file_path,
                language="unknown",
                errors=[f"Unsupported language for {file_path}"],
            )

        # Get parser and parse
        parser = self._get_parser(language)
        if not parser:
            return FileAnalysis(
                file_path=file_path,
                language=language,
                errors=[f"No parser available for {language}"],
            )

        source_bytes = source_code.encode("utf-8")
        tree = parser.parse(source_bytes)

        # Get queries
        queries = self._get_queries(language)

        # Extract entities
        analysis = FileAnalysis(file_path=file_path, language=language)

        for query_type, query in queries.items():
            try:
                entities = self._extract_entities(
                    tree, source_bytes, query, query_type, language
                )
                analysis.entities.extend(entities)

                # Categorize entities
                self._categorize_entities(entities, analysis, query_type)
            except Exception as e:
                analysis.errors.append(f"Error in {query_type} query: {e}")

        # Extract docstrings separately (special handling)
        self._extract_docstrings(tree, source_bytes, analysis, language)

        # Build qualified names and parent-child relationships
        self._build_hierarchy(analysis)

        return analysis

    def _extract_entities(
        self,
        tree: Tree,
        source_bytes: bytes,
        query: Query,
        query_type: str,
        language: str,
    ) -> list[CodeEntity]:
        """Extract entities from a tree-sitter query match."""
        entities = []
        cursor = QueryCursor(query)

        for match in cursor.matches(tree.root_node):
            entity = self._create_entity_from_match(
                match, source_bytes, query_type, language
            )
            if entity:
                entities.append(entity)

        return entities

    def _create_entity_from_match(
        self,
        match,
        source_bytes: bytes,
        query_type: str,
        language: str,
    ) -> CodeEntity | None:
        """Create a CodeEntity from a query match."""
        captures = match[1]  # Dictionary of capture_name -> list of nodes

        # Extract basic info based on query type
        if query_type in ("functions", "async_functions"):
            return self._create_function_entity(captures, source_bytes, language)
        elif query_type in ("classes", "structs", "enums", "interfaces", "impls"):
            return self._create_class_entity(captures, source_bytes, language, query_type)
        elif query_type == "variables":
            return self._create_variable_entity(captures, source_bytes, language)
        elif query_type == "imports":
            return self._create_import_entity(captures, source_bytes, language)
        elif query_type == "calls":
            return self._create_call_entity(captures, source_bytes, language)
        elif query_type == "comments":
            return self._create_comment_entity(captures, source_bytes, language)
        elif query_type == "methods":
            return self._create_method_entity(captures, source_bytes, language)

        return None

    def _create_function_entity(self, captures: dict, source_bytes: bytes, language: str) -> CodeEntity | None:
        """Create function entity from captures."""
        name_node = captures.get("function.name") or captures.get("method.name")
        if not name_node:
            return None

        name = name_node[0].text.decode("utf-8") if name_node else "anonymous"
        def_node = captures.get("function.def") or captures.get("function.arrow") or captures.get("function.expr") or captures.get("function.method") or captures.get("method.def")
        if not def_node:
            return None

        node = def_node[0]
        params_node = captures.get("function.params")
        return_type_node = captures.get("function.return_type") or captures.get("function.results")
        body_node = captures.get("function.body")

        metadata = {
            "parameters": params_node[0].text.decode("utf-8") if params_node else "",
            "return_type": return_type_node[0].text.decode("utf-8") if return_type_node else "",
        }

        if body_node:
            metadata["body_start"] = body_node[0].start_point[0] + 1
            metadata["body_end"] = body_node[0].end_point[0] + 1

        return CodeEntity(
            entity_type="function",
            name=name,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            source_text=source_bytes[node.start_byte:node.end_byte].decode("utf-8"),
            metadata=metadata,
        )

    def _create_class_entity(
        self, captures: dict, source_bytes: bytes, language: str, query_type: str
    ) -> CodeEntity | None:
        """Create class/struct/enum/interface entity from captures."""
        name_node = captures.get("class.name") or captures.get("struct.name") or captures.get("enum.name") or captures.get("interface.name") or captures.get("type.name")
        if not name_node:
            return None

        name = name_node[0].text.decode("utf-8")
        def_node = captures.get("class.def") or captures.get("struct.def") or captures.get("enum.def") or captures.get("interface.def") or captures.get("impl.def")
        if not def_node:
            return None

        node = def_node[0]

        metadata = {
            "kind": query_type.rstrip("s"),  # class, struct, enum, interface, impl
        }

        # Handle superclass/interfaces
        super_node = captures.get("class.superclasses") or captures.get("class.superclass") or captures.get("struct.superclass") or captures.get("interface.extends")
        if super_node:
            metadata["superclasses"] = super_node[0].text.decode("utf-8")

        type_params_node = captures.get("class.type_params") or captures.get("struct.generics") or captures.get("function.generics") or captures.get("function.type_params")
        if type_params_node:
            metadata["type_parameters"] = type_params_node[0].text.decode("utf-8")

        return CodeEntity(
            entity_type="class",
            name=name,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            source_text=source_bytes[node.start_byte:node.end_byte].decode("utf-8"),
            metadata=metadata,
        )

    def _create_variable_entity(self, captures: dict, source_bytes: bytes, language: str) -> CodeEntity | None:
        """Create variable entity from captures."""
        # Handle different variable capture patterns
        name_node = captures.get("variable.name")
        if not name_node:
            return None

        name = name_node[0].text.decode("utf-8")
        assign_node = captures.get("variable.assign") or captures.get("variable.annotated") or captures.get("variable.decl") or captures.get("variable.lexical") or captures.get("variable.let") or captures.get("variable.const") or captures.get("variable.short")
        if not assign_node:
            return None

        node = assign_node[0]

        metadata = {}
        type_node = captures.get("variable.type")
        if type_node:
            metadata["type"] = type_node[0].text.decode("utf-8")

        value_node = captures.get("variable.value")
        if value_node:
            metadata["value"] = value_node[0].text.decode("utf-8")

        return CodeEntity(
            entity_type="variable",
            name=name,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            source_text=source_bytes[node.start_byte:node.end_byte].decode("utf-8"),
            metadata=metadata,
        )

    def _create_import_entity(self, captures: dict, source_bytes: bytes, language: str) -> CodeEntity | None:
        """Create import entity from captures."""
        # Handle various import patterns
        module_node = captures.get("import.module") or captures.get("import.from_module") or captures.get("import.source") or captures.get("import.path") or captures.get("import.name") or captures.get("include.path")
        if not module_node:
            return None

        module = module_node[0].text.decode("utf-8").strip('"\'')

        stmt_node = captures.get("import.stmt") or captures.get("import.from_stmt") or captures.get("import.stmt") or captures.get("import.group") or captures.get("include.stmt")
        if not stmt_node:
            return None

        node = stmt_node[0]

        metadata = {
            "module": module,
        }

        # Named imports
        named_node = captures.get("import.named") or captures.get("import.specifier") or captures.get("import.tree") or captures.get("import.list")
        if named_node:
            metadata["named"] = named_node[0].text.decode("utf-8")

        alias_node = captures.get("import.alias") or captures.get("import.name")
        if alias_node and alias_node != module_node:
            metadata["alias"] = alias_node[0].text.decode("utf-8")

        return CodeEntity(
            entity_type="import",
            name=module,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            source_text=source_bytes[node.start_byte:node.end_byte].decode("utf-8"),
            metadata=metadata,
        )

    def _create_call_entity(self, captures: dict, source_bytes: bytes, language: str) -> CodeEntity | None:
        """Create function call entity from captures."""
        func_name_node = captures.get("call.func_name") or captures.get("call.method_name")
        if not func_name_node:
            return None

        func_name = func_name_node[0].text.decode("utf-8")
        call_node = captures.get("call.expr") or captures.get("call.method") or captures.get("call.object_method")
        if not call_node:
            return None

        node = call_node[0]

        metadata = {
            "function": func_name,
        }

        # Object for method calls
        obj_node = captures.get("call.object")
        if obj_node:
            metadata["object"] = obj_node[0].text.decode("utf-8")

        args_node = captures.get("call.args")
        if args_node:
            metadata["arguments"] = args_node[0].text.decode("utf-8")

        type_args_node = captures.get("call.type_args")
        if type_args_node:
            metadata["type_arguments"] = type_args_node[0].text.decode("utf-8")

        return CodeEntity(
            entity_type="call",
            name=func_name,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            source_text=source_bytes[node.start_byte:node.end_byte].decode("utf-8"),
            metadata=metadata,
        )

    def _create_comment_entity(self, captures: dict, source_bytes: bytes, language: str) -> CodeEntity | None:
        """Create comment entity from captures."""
        comment_node = captures.get("comment")
        if not comment_node:
            return None

        node = comment_node[0]
        text = source_bytes[node.start_byte:node.end_byte].decode("utf-8")

        return CodeEntity(
            entity_type="comment",
            name=f"comment_line_{node.start_point[0] + 1}",
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            source_text=text,
            metadata={"text": text.lstrip("# /").strip()},
        )

    def _create_method_entity(self, captures: dict, source_bytes: bytes, language: str) -> CodeEntity | None:
        """Create method entity from captures."""
        return self._create_function_entity(captures, source_bytes, language)

    def _extract_docstrings(self, tree: Tree, source_bytes: bytes, analysis: FileAnalysis, language: str) -> None:
        """Extract docstrings from the AST."""
        if language == "python":
            # Python docstrings are string literals at the start of functions/classes/modules
            query_str = """
                (expression_statement
                    (string) @docstring
                    (#match? @docstring "^(\"\"\")|('''")
                )
            """
            try:
                module = __import__("tree_sitter_python")
                ts_language = Language(module.language())
                query = Query(ts_language, query_str)
                cursor = QueryCursor(query)

                for match in cursor.matches(tree.root_node):
                    doc_node = match[1].get("docstring")
                    if doc_node:
                        node = doc_node[0]
                        text = source_bytes[node.start_byte:node.end_byte].decode("utf-8")
                        entity = CodeEntity(
                            entity_type="docstring",
                            name=f"docstring_line_{node.start_point[0] + 1}",
                            start_line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                            start_byte=node.start_byte,
                            end_byte=node.end_byte,
                            source_text=text,
                            metadata={"text": text.strip('"\'')},
                        )
                        analysis.docstrings.append(entity)
            except Exception:
                pass

    def _categorize_entities(self, entities: list[CodeEntity], analysis: FileAnalysis, query_type: str) -> None:
        """Categorize entities into appropriate lists."""
        for entity in entities:
            if query_type in ("functions", "async_functions", "methods"):
                analysis.functions.append(entity)
            elif query_type in ("classes", "structs", "enums", "interfaces", "impls"):
                analysis.classes.append(entity)
            elif query_type == "variables":
                analysis.variables.append(entity)
            elif query_type == "imports":
                analysis.imports.append(entity)
            elif query_type == "calls":
                analysis.calls.append(entity)
            elif query_type == "comments":
                analysis.comments.append(entity)

    def _build_hierarchy(self, analysis: FileAnalysis) -> None:
        """Build parent-child relationships and qualified names."""
        # Sort entities by start position
        all_entities = sorted(analysis.entities, key=lambda e: (e.start_line, e.start_byte))

        # Build hierarchy - simple approach: parent is the last entity that starts before this one and ends after
        for entity in all_entities:
            # Find parent
            parent = None
            for potential_parent in reversed(all_entities):
                if (potential_parent.start_line <= entity.start_line and
                    potential_parent.end_line >= entity.end_line and
                    potential_parent != entity):
                    parent = potential_parent
                    break

            if parent:
                entity.parent_entity = parent
                parent.children.append(entity)

            # Build qualified name
            if parent and parent.qualified_name:
                entity.qualified_name = f"{parent.qualified_name}.{entity.name}"
            elif parent:
                entity.qualified_name = f"{parent.name}.{entity.name}"
            else:
                entity.qualified_name = entity.name

    def extract_imports(self, file_path: str) -> list[CodeEntity]:
        """Extract only imports from a file."""
        analysis = self.analyze_file(file_path)
        return analysis.imports

    def extract_functions(self, file_path: str) -> list[CodeEntity]:
        """Extract only functions from a file."""
        analysis = self.analyze_file(file_path)
        return analysis.functions

    def extract_classes(self, file_path: str) -> list[CodeEntity]:
        """Extract only classes from a file."""
        analysis = self.analyze_file(file_path)
        return analysis.classes

    def extract_calls(self, file_path: str) -> list[CodeEntity]:
        """Extract only function calls from a file."""
        analysis = self.analyze_file(file_path)
        return analysis.calls


def analyze_file(file_path: str) -> FileAnalysis:
    """Convenience function to analyze a single file."""
    locator = StaticLocator()
    return locator.analyze_file(file_path)
