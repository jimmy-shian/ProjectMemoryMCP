"""Workflow for rescanning changed files."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from project_memory_mcp.db.connection import get_session
from project_memory_mcp.db.models import (
    AnalysisStatus,
    File,
    GraphEdge,
    LLMAnalysisRecord,
    OperationsHistory,
    Symbol,
    Equation,
    Variable,
)
from project_memory_mcp.llm_analysis.analyzer import get_analyzer
from project_memory_mcp.static_analysis.file_scanner import FileScanner
from project_memory_mcp.static_analysis.static_locator import StaticLocator


class RescanChangedFilesWorkflow:
    """
    Workflow for incrementally rescanning only changed files.

    Steps:
    1. Get current file hashes from database
    2. Scan project directory for current files
    3. Compare hashes to detect changed/new/deleted files
    4. Update changed files (re-extract static structure, create new LLM tasks)
    5. Remove deleted files from database
    6. Update graph edges
    """

    def __init__(self, project_path: str, config: dict[str, Any] | None = None):
        self.project_path = Path(project_path).resolve()
        self.config = config or {}
        self.exclude_patterns = set(self.config.get("exclude_patterns", []))
        self.scanner = FileScanner(
            str(self.project_path),
            exclude_patterns=self.exclude_patterns,
        )
        self.locator = StaticLocator()
        self.analyzer = get_analyzer(mode="agent_driven")

    def _build_analysis_record(self, task: dict[str, Any]) -> LLMAnalysisRecord:
        """Build a PENDING LLMAnalysisRecord row from a task dict (matches IndexRepositoryWorkflow)."""
        model_name = (
            self.config.get("llm_model")
            or getattr(getattr(self.analyzer, "settings", None), "llm_model", None)
            or "unknown"
        )
        return LLMAnalysisRecord(
            target_type=task["task_type"],
            target_id=int(task["task_id"].split("_")[-1]),
            prompt_name=task["prompt_name"],
            prompt_version=task["prompt_version"],
            model_name=model_name,
            input_context_hash=task["context_hash"],
            output_json="{}",
            confidence=0.0,
            status=AnalysisStatus.PENDING.value,
        )

    def _create_file_analysis_record(self, file_record: File) -> LLMAnalysisRecord:
        """Build a PENDING file-level LLMAnalysisRecord for a file (caller session.add's it)."""
        task = self.analyzer.create_analysis_task(
            task_id=f"file_{file_record.id}",
            task_type="file",
            target_path=file_record.path,
            context={"file_id": file_record.id},
        )
        return self._build_analysis_record(task)

    async def execute(self) -> dict[str, Any]:
        """Execute the rescan workflow."""
        results = {
            "files_checked": 0,
            "files_changed": 0,
            "files_added": 0,
            "files_deleted": 0,
            "symbols_updated": 0,
            "equations_updated": 0,
            "errors": [],
        }

        # Step 1: Get previous file hashes from DB
        print("Step 1: Loading previous file state...")
        previous_files = await self._get_previous_file_hashes()

        # Step 2: Scan current files
        print("Step 2: Scanning current files...")
        current_file_infos = self.scanner.scan()
        results["files_checked"] = len(current_file_infos)

        # Step 3: Compare and process changes
        print("Step 3: Processing changes...")
        current_files_map = {f.relative_path: f for f in current_file_infos}

        # Process changed and new files
        for rel_path, file_info in current_files_map.items():
            old_hash = previous_files.get(rel_path)
            if old_hash is None:
                # New file
                await self._process_new_file(file_info, results)
                results["files_added"] += 1
            elif old_hash != file_info.hash:
                # Changed file
                await self._process_changed_file(file_info, results)
                results["files_changed"] += 1

        # Process deleted files
        for rel_path, old_hash in previous_files.items():
            if rel_path not in current_files_map:
                await self._process_deleted_file(rel_path, results)
                results["files_deleted"] += 1

        # Step 4: Update graph edges
        print("Step 4: Updating graph edges...")
        await self._update_graph_edges()

        # Step 5: Refresh the staleness snapshot to reflect the reconciled DB
        # state, so the next tool call no longer reports these same changes.
        print("Step 5: Refreshing staleness snapshot...")
        try:
            from project_memory_mcp.utils.staleness_checker import refresh_snapshot_async

            await refresh_snapshot_async(self.project_path)
        except Exception as e:
            results["errors"].append(f"Error refreshing staleness snapshot: {e}")

        # Record operation
        await self._record_operation("rescan", results)

        return results

    async def _get_previous_file_hashes(self) -> dict[str, str]:
        """Get file hashes from database."""
        async with get_session() as session:
            stmt = select(File.path, File.hash)
            result = await session.execute(stmt)
            return {row.path: row.hash for row in result.all()}

    async def _process_new_file(self, file_info, results: dict[str, Any]) -> None:
        """Process a newly added file."""
        async with get_session() as session:
            file_record = File(
                path=file_info.relative_path,
                filename=file_info.filename,
                extension=file_info.extension,
                language=file_info.language,
                file_type="source" if file_info.is_source else "other",
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

            # Create a PENDING LLMAnalysisRecord for this new file
            session.add(self._create_file_analysis_record(file_record))

            # Extract static structure
            if file_info.is_source and file_info.language:
                await self._extract_and_store_structure(file_record, file_info, session)

    async def _process_changed_file(self, file_info, results: dict[str, Any]) -> None:
        """Process a changed file - update existing record and re-extract."""
        async with get_session() as session:
            stmt = select(File).where(File.path == file_info.relative_path)
            result = await session.execute(stmt)
            file_record = result.scalar_one_or_none()

            if not file_record:
                return

            # Update file record
            file_record.hash = file_info.hash
            file_record.last_modified = datetime.fromtimestamp(file_info.last_modified)
            file_record.size_bytes = file_info.size_bytes
            file_record.updated_at = datetime.utcnow()
            file_record.analysis_status = AnalysisStatus.PENDING.value

            # Remove old symbols, equations, edges for this file (also deletes stale
            # LLMAnalysisRecord rows for the file + its symbols, so the background
            # loop can no longer pick up the old completed/failed records).
            await self._clear_file_data(file_record.id, session)

            # Re-create a PENDING LLMAnalysisRecord so server_driven/background loop
            # and get_analysis_progress see this file as pending (mirrors initial scan).
            session.add(self._create_file_analysis_record(file_record))

            # Re-extract static structure
            if file_info.is_source and file_info.language:
                await self._extract_and_store_structure(file_record, file_info, session)

    async def _process_deleted_file(self, rel_path: str, results: dict[str, Any]) -> None:
        """Process a deleted file - remove from database."""
        async with get_session() as session:
            stmt = select(File).where(File.path == rel_path)
            result = await session.execute(stmt)
            file_record = result.scalar_one_or_none()

            if file_record:
                # Delete related data
                await self._clear_file_data(file_record.id, session)

                # Delete file record
                await session.delete(file_record)

    async def _clear_file_data(self, file_id: int, session) -> None:
        """Clear all data associated with a file."""
        # Get symbol IDs for this file
        stmt = select(Symbol.id).where(Symbol.file_id == file_id)
        result = await session.execute(stmt)
        symbol_ids = [row[0] for row in result.all()]

        # Get equation IDs for this file
        stmt = select(Equation.id).where(Equation.file_id == file_id)
        result = await session.execute(stmt)
        equation_ids = [row[0] for row in result.all()]

        # Get variable IDs for this file
        stmt = select(Variable.id).where(Variable.file_id == file_id)
        result = await session.execute(stmt)
        variable_ids = [row[0] for row in result.all()]

        # Delete graph edges involving file, symbols, equations, variables
        targets = []
        if symbol_ids:
            targets.append((GraphEdge.source_type == "symbol") & (GraphEdge.source_id.in_(symbol_ids)))
            targets.append((GraphEdge.target_type == "symbol") & (GraphEdge.target_id.in_(symbol_ids)))
        if equation_ids:
            targets.append((GraphEdge.source_type == "equation") & (GraphEdge.source_id.in_(equation_ids)))
            targets.append((GraphEdge.target_type == "equation") & (GraphEdge.target_id.in_(equation_ids)))
        if variable_ids:
            targets.append((GraphEdge.source_type == "variable") & (GraphEdge.source_id.in_(variable_ids)))
            targets.append((GraphEdge.target_type == "variable") & (GraphEdge.target_id.in_(variable_ids)))
        
        targets.append((GraphEdge.source_type == "file") & (GraphEdge.source_id == file_id))
        targets.append((GraphEdge.target_type == "file") & (GraphEdge.target_id == file_id))

        from sqlalchemy import or_
        if targets:
            stmt = delete(GraphEdge).where(or_(*targets))
            await session.execute(stmt)

        # Mark LLM analysis records as stale instead of deleting
        if symbol_ids:
            stmt = select(LLMAnalysisRecord).where(
                (LLMAnalysisRecord.target_type == "symbol") & (LLMAnalysisRecord.target_id.in_(symbol_ids))
            )
            records = (await session.execute(stmt)).scalars().all()
            for r in records:
                r.status = "stale"
        if equation_ids:
            stmt = select(LLMAnalysisRecord).where(
                (LLMAnalysisRecord.target_type == "equation") & (LLMAnalysisRecord.target_id.in_(equation_ids))
            )
            records = (await session.execute(stmt)).scalars().all()
            for r in records:
                r.status = "stale"
        
        stmt = select(LLMAnalysisRecord).where(
            (LLMAnalysisRecord.target_type == "file") & (LLMAnalysisRecord.target_id == file_id)
        )
        records = (await session.execute(stmt)).scalars().all()
        for r in records:
            r.status = "stale"

        # Delete variables, equations, symbols
        if variable_ids:
            stmt = delete(Variable).where(Variable.id.in_(variable_ids))
            await session.execute(stmt)
        if equation_ids:
            stmt = delete(Equation).where(Equation.id.in_(equation_ids))
            await session.execute(stmt)
        if symbol_ids:
            stmt = delete(Symbol).where(Symbol.id.in_(symbol_ids))
            await session.execute(stmt)

    def _find_enclosing_symbol(self, call_entity, analysis) -> Any | None:
        """Find the symbol that encloses a call."""
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
        for func in analysis.functions:
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
                results["equations_updated"] += 1

    async def _create_static_edges(
        self,
        file_record: File,
        analysis,
        session,
        new_symbols_info: dict[str, int],
    ) -> None:
        """Create static graph edges for DEFINES, IMPORTS, CALLS."""
        file_id = file_record.id

        # DEFINES edges
        for qualified_name, symbol_id in new_symbols_info.items():
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

        # IMPORTS edges
        seen_imports = set()
        for imp in analysis.imports:
            key = f"IMPORTS:{imp.name}"
            if key in seen_imports:
                continue
            seen_imports.add(key)
            edge = GraphEdge(
                source_type="file",
                source_id=file_id,
                target_type="file",
                target_id=0,
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

        # CALLS edges
        seen_calls = set()
        for call in analysis.calls:
            caller = self._find_enclosing_symbol(call, analysis)
            if caller and caller.qualified_name in new_symbols_info:
                caller_id = new_symbols_info[caller.qualified_name]
                ckey = f"CALLS:{caller_id}:{call.name}"
                if ckey in seen_calls:
                    continue
                seen_calls.add(ckey)
                edge = GraphEdge(
                    source_type="symbol",
                    source_id=caller_id,
                    target_type="symbol",
                    target_id=0,
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

    async def _extract_and_store_structure(
        self,
        file_record: File,
        file_info,
        session,
        results: dict[str, Any] | None = None,
    ) -> None:
        """Extract static structure and store in database."""
        try:
            analysis = self.locator.analyze_file(file_info.path)
            new_symbols_info = {}
            results_dict = {"symbols_updated": 0, "equations_updated": 0}

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
                new_symbols_info[func.qualified_name] = symbol.id
                results_dict["symbols_updated"] += 1

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
                new_symbols_info[cls.qualified_name] = symbol.id
                results_dict["symbols_updated"] += 1

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
                new_symbols_info[var.qualified_name] = symbol.id
                results_dict["symbols_updated"] += 1

            # Update results if provided
            if results is not None:
                results["symbols_updated"] += results_dict["symbols_updated"]

            # Create static edges (DEFINES, IMPORTS, CALLS)
            await self._create_static_edges(file_record, analysis, session, new_symbols_info)

            # Detect equations
            await self._detect_equations(file_record, analysis, session, results_dict)
            if results is not None:
                results["equations_updated"] += results_dict["equations_updated"]

        except Exception as e:
            print(f"Error extracting static structure for {file_record.path}: {e}")

    async def _update_graph_edges(self) -> None:
        """Update graph edges after changes.

        IMPORTS and CALLS edges are re-resolved in place against the current
        file/symbol maps. Each edge keeps its existing (already-unique)
        ``target_id`` until a fresh resolution is computed, so we never issue
        a blanket ``UPDATE ... SET target_id=0`` that would collapse distinct
        edges from the same source onto the same key and trip the
        ``uq_edge_unique`` constraint. Edges that can no longer be resolved,
        or that would duplicate a just-resolved edge, are deleted instead.
        """
        from sqlalchemy import delete, select

        async with get_session() as session:
            # 1. Clear LLM-derived edges database-wide
            await session.execute(delete(GraphEdge).where(
                GraphEdge.edge_type.in_([
                    "USES_EQUATION", "EQUATION_INPUT", "EQUATION_OUTPUT",
                    "EQUATION_INTERMEDIATE", "EQUATION_DEPENDS_ON"
                ])
            ))

            # 2. Resolve imports database-wide (in place, no blanket reset)
            files_result = await session.execute(select(File))
            file_map = {f.path: f for f in files_result.scalars().all()}

            def resolve_import(module_name: str) -> int | None:
                for f_path, f_rec in file_map.items():
                    if f_path.replace("/", ".").replace(".py", "") == module_name:
                        return f_rec.id
                    if f_rec.filename.replace(".py", "") == module_name.rsplit(".", maxsplit=1)[-1]:
                        return f_rec.id
                return None

            import_edges = (
                await session.execute(select(GraphEdge).where(GraphEdge.edge_type == "IMPORTS"))
            ).scalars().all()
            deleted = self._dedup_resolve_edges(
                import_edges,
                lambda ev: ev.replace("Import: ", "").strip(),
                lambda name: resolve_import(name),
            )
            if deleted:
                await session.execute(
                    delete(GraphEdge).where(GraphEdge.id.in_(deleted))
                )

            # 3. Resolve calls database-wide (in place, no blanket reset)
            symbols_result = await session.execute(select(Symbol))
            symbol_map = {s.qualified_name or s.name: s for s in symbols_result.scalars().all()}

            call_edges = (
                await session.execute(select(GraphEdge).where(GraphEdge.edge_type == "CALLS"))
            ).scalars().all()
            deleted = self._dedup_resolve_edges(
                call_edges,
                lambda ev: ev.replace("Call to ", "").strip(),
                lambda name: symbol_map[name].id if name in symbol_map else None,
            )
            if deleted:
                await session.execute(
                    delete(GraphEdge).where(GraphEdge.id.in_(deleted))
                )

            # 4. Build LLM-derived edges database-wide
            await add_llm_derived_edges(session)

    @staticmethod
    def _dedup_resolve_edges(
        edges,
        extract_name,
        resolve_target_id,
    ) -> list[int]:
        """Re-resolve edges in place, returning ids of edges to delete.

        For each edge, ``extract_name(edge.evidence)`` yields the lookup key and
        ``resolve_target_id(name)`` yields the new target id (or ``None`` if
        unresolvable). Edges that can't be resolved, or that would duplicate a
        just-resolved edge (same ``uq_edge_unique`` key), are collected for
        deletion instead of being collapsed onto a shared key.
        """
        seen: set[tuple[str, int, str, int, str]] = set()
        to_delete: list[int] = []
        for edge in edges:
            name = extract_name(edge.evidence or "")
            tid = resolve_target_id(name)
            if not tid:
                to_delete.append(edge.id)
                continue
            key = (
                edge.source_type, edge.source_id,
                edge.target_type, tid, edge.edge_type,
            )
            if key in seen:
                to_delete.append(edge.id)
                continue
            seen.add(key)
            edge.target_id = tid
            edge.confidence = 0.9
        return to_delete

    async def _record_operation(self, operation_type: str, results: dict[str, Any]) -> None:
        """Record the rescan operation."""
        async with get_session() as session:
            record = OperationsHistory(
                operation_type=operation_type,
                user_request=f"Rescan changed files in {self.project_path}",
                impact_summary=json.dumps(results),
                status="completed",
            )
            session.add(record)


async def rescan_changed_files(project_path: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Convenience function to run the rescan workflow."""
    workflow = RescanChangedFilesWorkflow(project_path, config)
    return await workflow.execute()


async def add_llm_derived_edges(session) -> None:
    """Add edges derived from completed, non-stale LLM analysis records."""
    from sqlalchemy import select
    from project_memory_mcp.db.models import LLMAnalysisRecord, Symbol, Equation, Variable, GraphEdge, File
    import json

    async def add_edge_if_not_exists(
        source_type: str,
        source_id: int,
        target_type: str,
        target_id: int,
        edge_type: str,
        evidence: str,
        confidence: float,
    ) -> None:
        stmt = select(GraphEdge).where(
            (GraphEdge.source_type == source_type) &
            (GraphEdge.source_id == source_id) &
            (GraphEdge.target_type == target_type) &
            (GraphEdge.target_id == target_id) &
            (GraphEdge.edge_type == edge_type)
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing:
            return

        edge = GraphEdge(
            source_type=source_type,
            source_id=source_id,
            target_type=target_type,
            target_id=target_id,
            edge_type=edge_type,
            evidence=evidence,
            confidence=confidence,
            created_by="llm_analyzer"
        )
        try:
            async with session.begin_nested():
                session.add(edge)
                await session.flush()
        except Exception:
            pass

    # 1. Fetch completed, non-stale analysis records
    stmt = select(LLMAnalysisRecord).where(LLMAnalysisRecord.status == "completed")
    records = (await session.execute(stmt)).scalars().all()

    for record in records:
        try:
            output_data = json.loads(record.output_json) if isinstance(record.output_json, str) else record.output_json
        except Exception:
            continue

        if not output_data:
            continue

        # For Symbol records
        if record.target_type == "symbol":
            # Verify target Symbol and File still exist and are valid
            sym_stmt = select(Symbol).where(Symbol.id == record.target_id)
            symbol = (await session.execute(sym_stmt)).scalar_one_or_none()
            if not symbol:
                continue

            file_stmt = select(File).where(File.id == symbol.file_id)
            file_rec = (await session.execute(file_stmt)).scalar_one_or_none()
            if not file_rec:
                continue

            related_eqs = output_data.get("related_equations", [])
            for eq_name in related_eqs:
                if not eq_name:
                    continue
                # Try finding Equation in the same file first
                eq_stmt = select(Equation).where(
                    (Equation.file_id == symbol.file_id) & (Equation.name == eq_name)
                )
                eq_rec = (await session.execute(eq_stmt)).scalar_one_or_none()
                if not eq_rec:
                    # Fallback to global query
                    eq_stmt = select(Equation).where(Equation.name == eq_name)
                    eq_rec = (await session.execute(eq_stmt)).scalar_one_or_none()

                if eq_rec:
                    await add_edge_if_not_exists(
                        source_type="symbol",
                        source_id=symbol.id,
                        target_type="equation",
                        target_id=eq_rec.id,
                        edge_type="USES_EQUATION",
                        evidence=f"LLM symbol analysis of {symbol.name}",
                        confidence=record.confidence or 0.8,
                    )

        # For Equation records
        elif record.target_type == "equation":
            # Verify target Equation and File still exist
            eq_stmt = select(Equation).where(Equation.id == record.target_id)
            equation = (await session.execute(eq_stmt)).scalar_one_or_none()
            if not equation:
                continue

            file_stmt = select(File).where(File.id == equation.file_id)
            file_rec = (await session.execute(file_stmt)).scalar_one_or_none()
            if not file_rec:
                continue

            # We extract variables: Inputs, Outputs, Intermediate, Constants
            var_groups = [
                ("inputs", "input", "EQUATION_INPUT"),
                ("outputs", "output", "EQUATION_OUTPUT"),
                ("intermediate_variables", "intermediate", "EQUATION_INTERMEDIATE"),
                ("constants", "constant", "EQUATION_DEPENDS_ON")
            ]

            for group_key, var_role, edge_type in var_groups:
                var_names = output_data.get(group_key, [])
                for name in var_names:
                    if not name:
                        continue

                    # Upsert Variable using file_id, symbol_id, name, role
                    symbol_id = equation.symbol_id
                    var_stmt = select(Variable).where(
                        (Variable.file_id == equation.file_id) &
                        (Variable.symbol_id == symbol_id) &
                        (Variable.name == name) &
                        (Variable.role == var_role)
                    )
                    variable = (await session.execute(var_stmt)).scalar_one_or_none()

                    if not variable:
                        variable = Variable(
                            file_id=equation.file_id,
                            symbol_id=symbol_id,
                            name=name,
                            role=var_role,
                            confidence=record.confidence or 0.8,
                        )
                        session.add(variable)
                        await session.flush()

                    # Create directed edge: Equation -> Variable
                    await add_edge_if_not_exists(
                        source_type="equation",
                        source_id=equation.id,
                        target_type="variable",
                        target_id=variable.id,
                        edge_type=edge_type,
                        evidence=f"LLM equation analysis of {equation.name or 'unnamed'}",
                        confidence=record.confidence or 0.8,
                    )
