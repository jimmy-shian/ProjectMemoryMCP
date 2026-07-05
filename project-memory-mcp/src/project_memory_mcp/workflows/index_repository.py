"""Workflow for indexing a repository."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from project_memory_mcp.db.connection import get_session
from project_memory_mcp.db.models import (
    AnalysisStatus,
    Equation,
    File,
    GraphEdge,
    LLMAnalysisRecord,
    OperationsHistory,
    Symbol,
)
from project_memory_mcp.llm_analysis.analyzer import AnalysisStatus, get_analyzer
from project_memory_mcp.static_analysis.file_scanner import FileScanner
from project_memory_mcp.static_analysis.static_locator import StaticLocator
from project_memory_mcp.utils.config import load_config


class IndexRepositoryWorkflow:
    """
    Complete workflow for indexing a repository and building the knowledge graph.

    Steps:
    1. Scan files and create initial File records
    2. Extract static structure (symbols, imports, calls) via tree-sitter
    3. Create LLM analysis tasks for files, symbols, equations
    4. Wait for agent to submit analysis results (agent-driven mode)
    5. Build graph edges from static and LLM analysis
    6. Generate PROJECT_AGENT_MANUAL.md
    """

    def __init__(
        self,
        project_path: str,
        config: dict[str, Any] | None = None,
        config_path: str | Path | None = None,
    ):
        # Load config from file if provided
        if config_path:
            file_config = load_config(config_path)
            # Merge file config with provided config (provided config takes precedence)
            merged_config = {**file_config, **(config or {})}
            self.config = merged_config
        else:
            self.config = config or {}

        self.project_path = Path(project_path).resolve()
        self.exclude_patterns = set(self.config.get("exclude_patterns", []))
        self.scanner = FileScanner(
            str(self.project_path),
            exclude_patterns=self.exclude_patterns,
        )
        self.locator = StaticLocator()
        self.analyzer = get_analyzer(mode=self.config.get("llm_mode", "agent_driven"))

        # Workflow automation flags
        self.auto_index = self.config.get("workflow_auto_index", True)
        self.auto_build_graph = self.config.get("workflow_auto_build_graph", True)
        self.auto_generate_manual = self.config.get("workflow_auto_generate_manual", True)

        # State
        self.file_map: dict[str, File] = {}  # relative_path -> File
        self.symbol_map: dict[str, Symbol] = {}  # qualified_name -> Symbol
        self.equation_map: dict[str, Equation] = {}  # name -> Equation

    async def execute(self) -> dict[str, Any]:
        """
        Execute the full indexing workflow.

        Returns:
            Summary of indexing results
        """
        results = {
            "files_scanned": 0,
            "files_indexed": 0,
            "symbols_extracted": 0,
            "equations_found": 0,
            "analysis_tasks_created": 0,
            "errors": [],
        }

        # Step 1: Scan files
        print("Step 1: Scanning files...")
        file_infos = self.scanner.scan()
        results["files_scanned"] = len(file_infos)

        # Step 2: Create File records and extract static structure
        print("Step 2: Extracting static structure...")
        for file_info in file_infos:
            try:
                await self._process_file(file_info, results)
            except Exception as e:
                results["errors"].append(f"Error processing {file_info.relative_path}: {e}")

        # Step 3: Create analysis tasks for LLM
        print("Step 3: Creating LLM analysis tasks...")
        await self._create_analysis_tasks(results)

        # Step 4: Build graph edges (if enabled)
        if self.auto_build_graph:
            print("Step 4: Building graph edges...")
            await self._build_graph_edges()

        # Step 5: Generate manual (if enabled)
        if self.auto_generate_manual:
            print("Step 5: Generating PROJECT_AGENT_MANUAL...")
            await self._generate_manual()

        # Record operation
        await self._record_operation("index", results)

        return results

    @classmethod
    async def from_config_file(cls, config_path: str | Path) -> "IndexRepositoryWorkflow":
        """Create workflow instance from configuration file."""
        config = load_config(config_path)
        project_path = config.get("project_root", ".")
        return cls(project_path, config=config, config_path=config_path)

    @classmethod
    async def auto_execute(cls, config_path: str | Path) -> dict[str, Any]:
        """Load config from file and automatically execute the full pipeline."""
        workflow = await cls.from_config_file(config_path)
        return await workflow.execute()

    async def _process_file(self, file_info, results: dict[str, Any]) -> None:
        """Process a single file: create File record, extract static structure."""
        async with get_session() as session:
            # Check if file already exists
            from sqlalchemy import select
            stmt = select(File).where(File.path == file_info.relative_path)
            result = await session.execute(stmt)
            existing_file = result.scalar_one_or_none()

            if existing_file:
                # Update hash and modified time
                existing_file.hash = file_info.hash
                existing_file.last_modified = datetime.fromtimestamp(file_info.last_modified)
                existing_file.size_bytes = file_info.size_bytes
                existing_file.updated_at = datetime.utcnow()
                file_record = existing_file
            else:
                # Create new file record
                file_record = File(
                    path=file_info.relative_path,
                    filename=file_info.filename,
                    extension=file_info.extension,
                    language=file_info.language,
                    file_type=file_info.is_source and "source" or "other",
                    size_bytes=file_info.size_bytes,
                    hash=file_info.hash,
                    last_modified=datetime.fromtimestamp(file_info.last_modified),
                    is_source=file_info.is_source,
                    is_test=file_info.is_test,
                    is_config=file_info.is_config,
                    is_entrypoint=file_info.is_entrypoint,
                    analysis_status=AnalysisStatus.PENDING.value,
                )
                session.add(file_record)
                await session.flush()

            self.file_map[file_info.relative_path] = {  # type: ignore[assignment]
                "id": file_record.id,
                "path": file_record.path,
                "filename": file_record.filename,
                "language": file_record.language,
                "is_source": file_record.is_source,
            }
            results["files_indexed"] += 1

            # Extract static structure for source files
            if file_info.is_source and file_info.language:
                await self._extract_static_structure(file_record, file_info, session, results)

    async def _extract_static_structure(
        self,
        file_record: File,
        file_info,
        session,
        results: dict[str, Any],
    ) -> None:
        """Extract symbols, imports, calls using tree-sitter."""
        new_symbol_ids: list[int] = []
        try:
            analysis = self.locator.analyze_file(file_info.path)

            # Create Symbol records
            for func in analysis.functions:
                symbol = Symbol(
                    file_id=file_record.id,
                    name=func.name,
                    qualified_name=func.qualified_name,
                    symbol_type="function",
                    start_line=func.start_line,
                    end_line=func.end_line,
                    start_byte=func.start_byte,
                    end_byte=func.end_byte,
                    signature=func.metadata.get("parameters", ""),
                    docstring=func.metadata.get("docstring", ""),
                )
                session.add(symbol)
                await session.flush()
                self.symbol_map[func.qualified_name] = {
                    "id": symbol.id,
                    "name": symbol.name,
                    "qualified_name": symbol.qualified_name,
                    "symbol_type": "function",
                    "file_id": symbol.file_id,
                }
                new_symbol_ids.append(symbol.id)
                results["symbols_extracted"] += 1

            for cls in analysis.classes:
                symbol = Symbol(
                    file_id=file_record.id,
                    name=cls.name,
                    qualified_name=cls.qualified_name,
                    symbol_type="class",
                    start_line=cls.start_line,
                    end_line=cls.end_line,
                    start_byte=cls.start_byte,
                    end_byte=cls.end_byte,
                    docstring=cls.metadata.get("docstring", ""),
                )
                session.add(symbol)
                await session.flush()
                self.symbol_map[cls.qualified_name] = {
                    "id": symbol.id,
                    "name": symbol.name,
                    "qualified_name": symbol.qualified_name,
                    "symbol_type": "class",
                    "file_id": symbol.file_id,
                }
                new_symbol_ids.append(symbol.id)
                results["symbols_extracted"] += 1

            for var in analysis.variables:
                symbol = Symbol(
                    file_id=file_record.id,
                    name=var.name,
                    qualified_name=var.qualified_name,
                    symbol_type="variable",
                    start_line=var.start_line,
                    end_line=var.end_line,
                    start_byte=var.start_byte,
                    end_byte=var.end_byte,
                )
                session.add(symbol)
                await session.flush()
                self.symbol_map[var.qualified_name] = {
                    "id": symbol.id,
                    "name": symbol.name,
                    "qualified_name": symbol.qualified_name,
                    "symbol_type": "variable",
                    "file_id": symbol.file_id,
                }
                new_symbol_ids.append(symbol.id)
                results["symbols_extracted"] += 1

            # Create GraphEdges for static relationships (best-effort;
            # duplicate edges are skipped individually instead of rolling back
            # the whole file's symbols).
            await self._create_static_edges(
                file_record, analysis, session, new_symbol_ids
            )

            # Detect equations
            await self._detect_equations(file_record, analysis, session, results)

        except Exception as e:
            print(f"Error extracting static structure for {file_record.path}: {e}")

    async def _create_static_edges(
        self,
        file_record: File,
        analysis,
        session,
        new_symbol_ids: list[int] | None = None,
    ) -> None:
        """Create graph edges from static analysis.

        ``new_symbol_ids`` restricts the DEFINES edges to the symbols created in
        the current ``_extract_static_structure`` call, so we never re-emit edges
        for symbols that were already persisted for earlier files (which would
        trip the graph_edges UNIQUE constraint and rollback the symbols).
        """
        file_id = file_record.id

        # File -> Symbol edges (DEFINES) only for symbols newly created this file.
        for symbol_id in new_symbol_ids or []:
            edge = GraphEdge(
                source_type="file",
                source_id=file_id,
                target_type="symbol",
                target_id=symbol_id,
                edge_type="DEFINES",
                evidence="tree-sitter static analysis",
                confidence=1.0,
                created_by="static_locator",
            )
            try:
                async with session.begin_nested():
                    session.add(edge)
            except Exception:
                pass

        # Import edges (dedup by module name within this file)
        seen_imports: set[str] = set()
        for imp in analysis.imports:
            key = f"IMPORTS:{imp.name}"
            if key in seen_imports:
                continue
            seen_imports.add(key)
            edge = GraphEdge(
                source_type="file",
                source_id=file_id,
                target_type="file",
                target_id=0,  # Will be resolved later
                edge_type="IMPORTS",
                evidence=f"Import: {imp.name}",
                confidence=1.0,
                created_by="static_locator",
            )
            try:
                async with session.begin_nested():
                    session.add(edge)
            except Exception:
                pass

        # Call edges (dedup by caller+callname within this file)
        seen_calls: set[str] = set()
        for call in analysis.calls:
            caller = self._find_enclosing_symbol(call, analysis)
            if caller and caller.qualified_name in self.symbol_map:
                caller_symbol = self.symbol_map[caller.qualified_name]
                ckey = f"CALLS:{caller_symbol['id']}:{call.name}"
                if ckey in seen_calls:
                    continue
                seen_calls.add(ckey)
                edge = GraphEdge(
                    source_type="symbol",
                    source_id=caller_symbol["id"],
                    target_type="symbol",
                    target_id=0,  # Will be resolved later
                    edge_type="CALLS",
                    evidence=f"Call to {call.name}",
                    confidence=0.8,
                    created_by="static_locator",
                )
                try:
                    async with session.begin_nested():
                        session.add(edge)
                except Exception:
                    pass

    def _find_enclosing_symbol(self, call_entity, analysis) -> Optional:
        """Find the symbol that encloses a call."""
        # Simple heuristic: find the function/class that contains the call line
        for func in analysis.functions:
            if func.start_line <= call_entity.start_line <= func.end_line:
                return func
        for cls in analysis.classes:
            if cls.start_line <= call_entity.start_line <= cls.end_line:
                return cls
        return None

    async def _detect_equations(
        self,
        file_record: File,
        analysis,
        session,
        results: dict[str, Any],
    ) -> None:
        """Detect mathematical equations in the code."""
        # Use tree-sitter queries to find mathematical expressions
        # This is a simplified version - full implementation would use equation-specific queries
        for func in analysis.functions:
            # Check if function looks like it contains equations
            source = func.source_text.lower()
            equation_keywords = [
                "loss", "gradient", "optimizer", "backprop", "forward",
                "pid", "control", "matrix", "tensor", "eigen",
                "sigmoid", "softmax", "relu", "activation",
                "convolution", "pooling", "attention",
                "kalman", "filter", "estimate", "predict",
                "integral", "derivative", "differential",
            ]

            if any(kw in source for kw in equation_keywords):
                equation = Equation(
                    file_id=file_record.id,
                    symbol_id=None,  # Will be linked later
                    name=func.name,
                    equation_type="algorithmic",
                    expression=func.source_text[:500],
                    start_line=func.start_line,
                    end_line=func.end_line,
                    confidence=0.5,
                    inferred=True,
                )
                session.add(equation)
                await session.flush()
                self.equation_map[func.name] = {
                    "id": equation.id,
                    "name": equation.name,
                    "file_id": equation.file_id,
                }
                results["equations_found"] += 1

    async def _create_analysis_tasks(self, results: dict[str, Any]) -> None:
        """Create LLM analysis tasks for agent-driven mode.

        File/Symbol/Equation records are detached from any live session by the
        time we get here (each was flushed inside its own ``get_session()``
        block), so we re-query them inside a single fresh session to avoid
        ``DetachedInstanceError`` when reading ``is_source``/``id``/``path``.
        """
        from sqlalchemy import select

        tasks_created = 0

        async with get_session() as session:
            # File-level analysis tasks
            file_rows = (
                await session.execute(
                    select(File).where(File.is_source == True)  # noqa: E712
                )
            ).scalars().all()
            for file_record in file_rows:
                task = self.analyzer.create_analysis_task(
                    task_id=f"file_{file_record.id}",
                    task_type="file",
                    target_path=file_record.path,
                    context={"file_id": file_record.id},
                )
                record = self._build_analysis_record(task)
                session.add(record)
                tasks_created += 1

            # Symbol-level analysis tasks
            symbol_rows = (
                await session.execute(
                    select(Symbol).where(
                        Symbol.symbol_type.in_(["function", "method", "class"])
                    )
                )
            ).scalars().all()
            for symbol in symbol_rows:
                task = self.analyzer.create_analysis_task(
                    task_id=f"symbol_{symbol.id}",
                    task_type="symbol",
                    target_path=symbol.qualified_name,
                    target_name=symbol.name,
                    context={"symbol_id": symbol.id, "file_id": symbol.file_id},
                )
                record = self._build_analysis_record(task)
                session.add(record)
                tasks_created += 1

            # Equation-level analysis tasks
            equation_rows = (await session.execute(select(Equation))).scalars().all()
            for equation in equation_rows:
                task = self.analyzer.create_analysis_task(
                    task_id=f"equation_{equation.id}",
                    task_type="equation",
                    target_path=equation.name,
                    target_name=equation.name,
                    context={"equation_id": equation.id, "file_id": equation.file_id},
                )
                record = self._build_analysis_record(task)
                session.add(record)
                tasks_created += 1

        results["analysis_tasks_created"] = tasks_created

    def _build_analysis_record(self, task: dict[str, Any]) -> LLMAnalysisRecord:
        """Build an LLMAnalysisRecord row from a task dict."""
        return LLMAnalysisRecord(
            target_type=task["task_type"],
            target_id=int(task["task_id"].split("_")[-1]),
            prompt_name=task["prompt_name"],
            prompt_version=task["prompt_version"],
            model_name=self.config.get("llm_model", "unknown"),
            input_context_hash=task["context_hash"],
            output_json="{}",  # Will be filled when agent submits
            confidence=0.0,
            status=AnalysisStatus.PENDING.value,
        )

    async def _build_graph_edges(self) -> None:
        """Build complete graph edges from static and LLM analysis."""
        async with get_session() as session:
            from sqlalchemy import select

            # Resolve import edges to actual file IDs
            stmt = select(GraphEdge).where(GraphEdge.edge_type == "IMPORTS")
            result = await session.execute(stmt)
            import_edges = result.scalars().all()

            for edge in import_edges:
                # Try to find target file by module name
                evidence = edge.evidence or ""
                module_name = evidence.replace("Import: ", "").strip()
                target_file_id = self._resolve_import(module_name)
                if target_file_id:
                    edge.target_id = target_file_id
                    edge.confidence = 0.9

            # Resolve call edges to actual symbol IDs
            stmt = select(GraphEdge).where(GraphEdge.edge_type == "CALLS")
            result = await session.execute(stmt)
            call_edges = result.scalars().all()

            for edge in call_edges:
                evidence = edge.evidence or ""
                called_name = evidence.replace("Call to ", "").strip()
                target_symbol = self.symbol_map.get(called_name)
                if target_symbol:
                    edge.target_id = target_symbol["id"]
                    edge.confidence = 0.9

            # Add LLM-derived edges
            await self._add_llm_derived_edges(session)

    def _resolve_import(self, module_name: str) -> int | None:
        """Resolve an import module name to a File id (plain int)."""
        # Try direct path match
        for file_record in self.file_map.values():
            if file_record["path"].replace("/", ".").replace(".py", "") == module_name:
                return file_record["id"]
            # Try with just the filename
            if file_record["filename"].replace(".py", "") == module_name.rsplit(".", maxsplit=1)[-1]:
                return file_record["id"]
        return None

    async def _add_llm_derived_edges(self, session) -> None:
        """Add edges derived from LLM analysis."""
        # This would process completed LLMAnalysisRecords and create edges
        # For equations, variables, dependencies, etc.
        pass

    async def _generate_manual(self) -> None:
        """Generate PROJECT_AGENT_MANUAL.md"""
        # Delegate to GenerateManualWorkflow
        from project_memory_mcp.workflows.generate_manual import GenerateManualWorkflow
        manual_workflow = GenerateManualWorkflow(str(self.project_path))
        await manual_workflow.execute()

    async def _record_operation(self, operation_type: str, results: dict[str, Any]) -> None:
        """Record the indexing operation in history."""
        async with get_session() as session:
            record = OperationsHistory(
                operation_type=operation_type,
                user_request=f"Index repository at {self.project_path}",
                affected_files_json=json.dumps(list(self.file_map.keys())),
                impact_summary=json.dumps(results),
                status="completed",
            )
            session.add(record)


async def index_repository(
    project_path: str,
    config: dict[str, Any] | None = None,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Convenience function to run the indexing workflow."""
    workflow = IndexRepositoryWorkflow(project_path, config, config_path)
    return await workflow.execute()


async def auto_index_repository(config_path: str | Path) -> dict[str, Any]:
    """Load config from file and automatically execute the full pipeline."""
    return await IndexRepositoryWorkflow.auto_execute(config_path)
