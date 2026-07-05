"""Background LLM analysis loop workflow."""

import asyncio
import json
import logging
import traceback
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select

from project_memory_mcp.db.connection import get_session
from project_memory_mcp.db.models import (
    AnalysisStatus,
    Equation,
    File,
    LLMAnalysisRecord,
    Symbol,
)
from project_memory_mcp.llm_analysis.analyzer import get_analyzer

logger = logging.getLogger(__name__)


class BackgroundAnalysisRunner:
    """Manages the background loop status in memory."""

    def __init__(self):
        self.is_running = False
        self.current_task_id = ""
        self.last_error = None
        self._task = None

    def start(self, project_path: str) -> str:
        """Spawn the background task if not already running."""
        if self.is_running:
            return "Analysis loop is already running."

        self.is_running = True
        self.last_error = None
        self.current_task_id = ""
        self._task = asyncio.create_task(self._run_loop(project_path))
        return "Started analysis loop in the background."

    async def _run_loop(self, project_path: str) -> None:
        try:
            logger.info("Background analysis loop started.")
            analyzer = get_analyzer(mode="server_driven")

            if not analyzer._client:
                # Re-initialize the LLM client in case settings were updated
                analyzer._initialize_client()

            if not analyzer._client:
                raise RuntimeError("LLM client not initialized. Check your LLM settings/API keys.")

            # Iterate over each type of analysis layer
            for task_type in ("file", "symbol", "equation"):
                prompt_name = f"analyze_{task_type}"

                while True:
                    # Pick next pending record
                    async with get_session() as session:
                        stmt = (
                            select(LLMAnalysisRecord)
                            .where(
                                (LLMAnalysisRecord.target_type == task_type)
                                & (LLMAnalysisRecord.status == AnalysisStatus.PENDING.value)
                            )
                            .order_by(LLMAnalysisRecord.id)
                            .limit(1)
                        )
                        rec = (await session.execute(stmt)).scalar_one_or_none()

                        if not rec:
                            break  # No more pending tasks in this layer

                        self.current_task_id = f"{task_type}_{rec.target_id}"
                        target_id = rec.target_id

                        # Skip tasks whose target file lives under an archive path.
                        # Such records are typically stale leftovers from old scans
                        # and re-analyzing them wastes LLM calls on dead code.
                        if await self._target_is_archived(session, task_type, target_id):
                            rec.status = AnalysisStatus.FAILED.value
                            rec.output_json = json.dumps(
                                {"error": "skipped: target file is under _archive"}
                            )
                            await session.commit()
                            continue

                        # Build the context
                        context = await self._build_context(session, task_type, target_id, project_path)

                        if not context:
                            # Mark record as failed if target is missing
                            rec.status = AnalysisStatus.FAILED.value
                            rec.output_json = json.dumps({"error": f"{task_type} record missing from database"})
                            await session.commit()
                            continue

                    # Perform LLM analysis outside the database session to avoid holding locks
                    error_msg = ""
                    try:
                        logger.info(f"Analyzing {self.current_task_id} using {analyzer.settings.llm_model}")
                        result = await analyzer.analyze(prompt_name, context)
                        status_ok = bool(result and result.result)
                    except Exception as e:
                        logger.error(f"Error during analysis call: {e}")
                        result = None
                        status_ok = False
                        error_msg = str(e)

                    # Persist results in a fresh database session
                    async with get_session() as session:
                        # Fetch records again in the new session
                        stmt_rec = select(LLMAnalysisRecord).where(
                            (LLMAnalysisRecord.target_type == task_type)
                            & (LLMAnalysisRecord.target_id == target_id)
                        )
                        rec_db = (await session.execute(stmt_rec)).scalar_one_or_none()

                        if rec_db:
                            if status_ok and result:
                                # Apply changes to target table
                                if task_type == "file":
                                    stmt_t = select(File).where(File.id == target_id)
                                    target_rec = (await session.execute(stmt_t)).scalar_one_or_none()
                                    if target_rec:
                                        data = result.result or {}
                                        target_rec.purpose = data.get("purpose", "")
                                        target_rec.llm_summary = data.get("summary", "")
                                        target_rec.llm_confidence = data.get("confidence", 0.0)
                                        target_rec.is_core = data.get("is_core", False)
                                        target_rec.key_concepts = json.dumps(data.get("key_concepts", []), ensure_ascii=False)
                                        target_rec.risk_notes = json.dumps(data.get("risk_notes", []), ensure_ascii=False)
                                        target_rec.analysis_status = AnalysisStatus.COMPLETED.value
                                elif task_type == "symbol":
                                    stmt_t = select(Symbol).where(Symbol.id == target_id)
                                    target_rec = (await session.execute(stmt_t)).scalar_one_or_none()
                                    if target_rec:
                                        data = result.result or {}
                                        resp = data.get("responsibility", "")
                                        target_rec.llm_summary = resp
                                        target_rec.responsibility = resp
                                        target_rec.side_effects = str(data.get("side_effects", []))
                                        target_rec.confidence = data.get("confidence", 0.0)
                                else: # equation
                                    stmt_t = select(Equation).where(Equation.id == target_id)
                                    target_rec = (await session.execute(stmt_t)).scalar_one_or_none()
                                    if target_rec:
                                        data = result.result or {}
                                        target_rec.name = data.get("name", target_rec.name)
                                        target_rec.equation_type = data.get("equation_type", "unknown")
                                        target_rec.mathematical_meaning = data.get("mathematical_meaning", "")
                                        target_rec.physical_meaning = data.get("physical_meaning")
                                        target_rec.algorithmic_role = data.get("algorithmic_role", "")
                                        target_rec.inputs_json = json.dumps(data.get("inputs", []))
                                        target_rec.outputs_json = json.dumps(data.get("outputs", []))
                                        target_rec.intermediate_variables_json = json.dumps(data.get("intermediate_variables", []))
                                        target_rec.constants_json = json.dumps(data.get("constants", []))
                                        target_rec.units_json = json.dumps(data.get("units", {}))
                                        target_rec.assumptions = str(data.get("assumptions", []))
                                        target_rec.confidence = data.get("confidence", 0.0)

                                rec_db.output_json = json.dumps(result.result, ensure_ascii=False)
                                rec_db.confidence = result.confidence
                                rec_db.status = AnalysisStatus.COMPLETED.value
                            else:
                                rec_db.status = AnalysisStatus.FAILED.value
                                rec_db.output_json = json.dumps({"error": error_msg if not status_ok else "LLM returned empty result"})
                            
                            await session.commit()

            logger.info("Background analysis loop completed successfully.")

        except Exception as exc:
            self.last_error = f"{exc}\n{traceback.format_exc()}"
            logger.error(f"Error in background analysis loop: {self.last_error}")
        finally:
            self.is_running = False
            self.current_task_id = ""

    async def _target_is_archived(self, session, task_type: str, target_id: int) -> bool:
        """Return True if the target's parent file lives under an _archive path."""
        file_record = None
        if task_type == "file":
            file_record = (
                await session.execute(select(File).where(File.id == target_id))
            ).scalar_one_or_none()
        elif task_type == "symbol":
            symbol = (
                await session.execute(select(Symbol).where(Symbol.id == target_id))
            ).scalar_one_or_none()
            if symbol:
                file_record = (
                    await session.execute(select(File).where(File.id == symbol.file_id))
                ).scalar_one_or_none()
        elif task_type == "equation":
            equation = (
                await session.execute(select(Equation).where(Equation.id == target_id))
            ).scalar_one_or_none()
            if equation:
                file_record = (
                    await session.execute(select(File).where(File.id == equation.file_id))
                ).scalar_one_or_none()
        if not file_record:
            return False
        path = file_record.path or ""
        return ("_archive/" in path) or ("_archive\\" in path)

    async def _build_context(self, session, task_type: str, target_id: int, project_path: str) -> Optional[dict[str, Any]]:
        """Construct the context variables for the prompt."""
        from project_memory_mcp.static_analysis.static_locator import StaticLocator

        project_root = Path(project_path).resolve()

        def read_source(rel_path: str) -> str:
            try:
                return (project_root / rel_path).read_text(encoding="utf-8", errors="replace")
            except Exception:
                return ""

        if task_type == "file":
            stmt = select(File).where(File.id == target_id)
            file_record = (await session.execute(stmt)).scalar_one_or_none()
            if not file_record:
                return None
            rel_path = file_record.path
            language = file_record.language or "unknown"
            imports = ""
            symbols = ""
            if language != "unknown":
                try:
                    locator = StaticLocator()
                    analysis = locator.analyze_file(str(project_root / rel_path))
                    imports = ", ".join(sorted({i.name for i in (analysis.imports or [])}))
                    symbols = ", ".join(
                        sorted(
                            {f.name for f in (analysis.functions or [])}
                            | {c.name for c in (analysis.classes or [])}
                        )
                    )
                except Exception:
                    pass
            return {
                "task_id": f"file_{file_record.id}",
                "task_type": "file",
                "target_path": rel_path,
                "file_id": file_record.id,
                "file_path": rel_path,
                "language": language,
                "source_code": read_source(rel_path),
                "imports": imports,
                "symbols": symbols,
            }

        elif task_type == "symbol":
            stmt = select(Symbol).where(Symbol.id == target_id)
            symbol = (await session.execute(stmt)).scalar_one_or_none()
            if not symbol:
                return None
            stmt_f = select(File).where(File.id == symbol.file_id)
            file_record = (await session.execute(stmt_f)).scalar_one_or_none()
            rel_path = file_record.path if file_record else ""
            language = file_record.language if file_record else "unknown"
            sym_source = ""
            if rel_path:
                sym_source = read_source(rel_path)
            return {
                "task_id": f"symbol_{symbol.id}",
                "task_type": "symbol",
                "target_path": symbol.qualified_name or symbol.name,
                "target_name": symbol.name,
                "symbol_id": symbol.id,
                "file_id": symbol.file_id,
                "file_path": rel_path,
                "language": language,
                "symbol_name": symbol.name,
                "symbol_type": symbol.symbol_type,
                "signature": symbol.signature or "",
                "docstring": symbol.docstring or "",
                "parent_class": "",
                "source_code": sym_source,
                "called_functions": "",
                "calling_functions": "",
            }

        elif task_type == "equation":
            stmt = select(Equation).where(Equation.id == target_id)
            equation = (await session.execute(stmt)).scalar_one_or_none()
            if not equation:
                return None
            stmt_f = select(File).where(File.id == equation.file_id)
            file_record = (await session.execute(stmt_f)).scalar_one_or_none()
            rel_path = file_record.path if file_record else ""
            language = file_record.language if file_record else "unknown"
            return {
                "task_id": f"equation_{equation.id}",
                "task_type": "equation",
                "target_path": equation.name or "",
                "target_name": equation.name,
                "equation_id": equation.id,
                "file_id": equation.file_id,
                "file_path": rel_path,
                "language": language,
                "equation_name": equation.name or "",
                "containing_function": "",
                "containing_class": "",
                "expression": equation.expression or "",
                "surrounding_code": read_source(rel_path) if rel_path else "",
                "variables_in_scope": "",
            }


# Global runner instance
runner = BackgroundAnalysisRunner()
