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
        # Delete symbols (cascades to equations, variables via foreign keys)
        # Get symbol IDs for this file
        stmt = select(Symbol.id).where(Symbol.file_id == file_id)
        result = await session.execute(stmt)
        symbol_ids = [row[0] for row in result.all()]

        # Delete graph edges involving these symbols
        if symbol_ids:
            stmt = delete(GraphEdge).where(
                (GraphEdge.source_type == "symbol") & (GraphEdge.source_id.in_(symbol_ids)) |
                (GraphEdge.target_type == "symbol") & (GraphEdge.target_id.in_(symbol_ids))
            )
            await session.execute(stmt)

            # Delete LLM analysis records for these symbols
            stmt = delete(LLMAnalysisRecord).where(
                (LLMAnalysisRecord.target_type == "symbol") & (LLMAnalysisRecord.target_id.in_(symbol_ids))
            )
            await session.execute(stmt)

        # Delete graph edges for this file
        stmt = delete(GraphEdge).where(
            (GraphEdge.source_type == "file") & (GraphEdge.source_id == file_id) |
            (GraphEdge.target_type == "file") & (GraphEdge.target_id == file_id)
        )
        await session.execute(stmt)

        # Delete LLM analysis records for this file (target_type="file")
        stmt = delete(LLMAnalysisRecord).where(
            (LLMAnalysisRecord.target_type == "file") & (LLMAnalysisRecord.target_id == file_id)
        )
        await session.execute(stmt)

    async def _extract_and_store_structure(
        self,
        file_record: File,
        file_info,
        session,
    ) -> None:
        """Extract static structure and store in database."""
        # Similar to IndexRepositoryWorkflow._extract_static_structure
        # Simplified for now
        pass

    async def _update_graph_edges(self) -> None:
        """Update graph edges after changes."""
        # Rebuild edges for affected files
        pass

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
