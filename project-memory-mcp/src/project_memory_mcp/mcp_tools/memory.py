"""Memory tools for the Project Memory MCP server."""

from pathlib import Path
from typing import Any

from mcp.server import Server
from pydantic import BaseModel, Field


# Input/Output schemas
class BootstrapInput(BaseModel):
    project_path: str = Field(default=".", description="Path to the project root")
    mode: str = Field(default="agent_driven", description="LLM mode: agent_driven or server_driven")
    use_vector_similarity: bool = Field(default=False, description="Whether to use vector similarity")


class BootstrapOutput(BaseModel):
    created: bool
    memory_dir: str
    next_step: str


class PlanIndexingInput(BaseModel):
    project_path: str = Field(default=".", description="Path to the project root")


class PlanIndexingOutput(BaseModel):
    steps: list[str]
    estimated_files: int
    excluded_paths: list[str]


class ScanFilesInput(BaseModel):
    project_path: str = Field(default=".", description="Path to the project root")
    exclude_patterns: list[str] = Field(default_factory=list)


class ScanFilesOutput(BaseModel):
    files_found: int
    files_inserted: int
    skipped: list[str]


class GetNextAnalysisTaskInput(BaseModel):
    project_path: str = Field(default=".", description="Path to the project root")
    task_type: str = Field(default="file", description="Type of task: file, symbol, equation")


class GetNextAnalysisTaskOutput(BaseModel):
    task_id: str
    task_type: str
    file_path: str | None = None
    target_name: str | None = None
    # Full agent-driven prompt bundle: the external agent reads these and generates
    # a description/summary, then submits it via project_submit_*_analysis.
    system_prompt: str = ""
    user_prompt: str = ""
    output_schema_name: str = ""
    output_schema: dict[str, Any] = Field(default_factory=dict)
    has_more: bool = True


class SubmitFileAnalysisInput(BaseModel):
    task_id: str
    file_path: str
    analysis: dict[str, Any]


class SubmitFileAnalysisOutput(BaseModel):
    accepted: bool
    db_updated: bool
    next_step: str
    error: str | None = None
    reason: str | None = None


class SubmitSymbolAnalysisInput(BaseModel):
    task_id: str
    symbol_name: str
    analysis: dict[str, Any]


class SubmitSymbolAnalysisOutput(BaseModel):
    accepted: bool
    db_updated: bool
    next_step: str
    error: str | None = None
    reason: str | None = None


class SubmitEquationAnalysisInput(BaseModel):
    task_id: str
    equation_name: str
    analysis: dict[str, Any]


class SubmitEquationAnalysisOutput(BaseModel):
    accepted: bool
    db_updated: bool
    next_step: str
    error: str | None = None
    reason: str | None = None


class BuildGraphEdgesInput(BaseModel):
    project_path: str = Field(default=".", description="Path to the project root")


class BuildGraphEdgesOutput(BaseModel):
    edges_created: int
    low_confidence_edges: list[str]
    unresolved_edges: list[str]


class RescanChangedFilesInput(BaseModel):
    project_path: str = Field(default=".", description="Path to the project root")


class RescanChangedFilesOutput(BaseModel):
    files_checked: int
    files_changed: int
    files_added: int
    files_deleted: int


class GenerateManualInput(BaseModel):
    project_path: str = Field(default=".", description="Path to the project root")


class GenerateManualOutput(BaseModel):
    generated: bool
    manual_path: str
    sections: int


class StartAnalysisLoopInput(BaseModel):
    project_path: str = Field(default=".", description="Path to the project root")
    llm_provider: str | None = Field(default=None, description="LLM provider: anthropic, openai, google, myself")
    llm_api_key: str | None = Field(default=None, description="LLM API key")
    llm_model: str | None = Field(default=None, description="LLM model name")
    llm_api_base: str | None = Field(default=None, description="LLM API base URL")


class StartAnalysisLoopOutput(BaseModel):
    started: bool
    message: str


class GetAnalysisProgressInput(BaseModel):
    project_path: str = Field(default=".", description="Path to the project root")


class GetAnalysisProgressOutput(BaseModel):
    is_running: bool
    current_task_id: str
    last_error: str | None
    total_tasks: int
    pending_tasks: int
    completed_tasks: int
    failed_tasks: int



def _project_root(project_path: str) -> Path:
    """Resolve the project root, defaulting to cwd."""
    p = Path(project_path).resolve()
    return p


def _read_source(project_path: str, file_rel_path: str) -> str:
    """Read a source file from the project, returning empty string on error."""
    root = _project_root(project_path)
    full = root / file_rel_path
    try:
        return full.read_text(encoding="utf-8", errors="replace")
    except Exception:
        try:
            return Path(file_rel_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""


def _pydantic_json_schema(schema_class) -> dict[str, Any]:
    """Return the JSON Schema for a Pydantic v2 model class."""
    try:
        return schema_class.model_json_schema()
    except Exception:
        return {"type": "object"}


def _build_analysis_task_output(  # noqa: PLR0913
    *,
    analyzer,
    task_type: str,
    task_id: str,
    file_record,
    project_path: str = ".",
    symbol=None,
    equation=None,
) -> "GetNextAnalysisTaskOutput":
    """Construct the agent-driven task bundle with a fully formatted prompt.

    The MCP server performs NO LLM call here. It reads the source, formats the
    prompt chosen from BUILTIN_PROMPTS for the agent, and exposes the JSON
    Schema the agent must conform to when submitting via project_submit_*_analysis.
    """
    from project_memory_mcp.static_analysis.static_locator import StaticLocator

    prompt_name = f"analyze_{task_type}"
    template = analyzer.get_prompt(prompt_name)
    if not template:
        return GetNextAnalysisTaskOutput(
            task_id=task_id, task_type=task_type, has_more=True,
        )

    # Build the template context from the DB record + source file.
    rel_path = file_record.path if file_record else ""
    language = file_record.language if file_record else "unknown"

    ctx: dict[str, Any] = {
        "task_id": task_id,
        "task_type": task_type,
        "target_path": rel_path,
        "file_id": file_record.id if file_record else "",
        "file_path": rel_path,
        "language": language,
    }

    # Fetch a fresh static analysis to populate imports/symbols/surrounding_code.
    locator = StaticLocator()
    analysis = None
    if file_record and language != "unknown":
        try:
            analysis = locator.analyze_file(str(_project_root(project_path) / rel_path))
        except Exception:
            analysis = None

    if task_type == "file":
        imports = ", ".join(sorted({i.name for i in (analysis.imports if analysis else [])}))
        symbols_list = ", ".join(
            sorted({f.name for f in (analysis.functions if analysis else [])}
                   | {c.name for c in (analysis.classes if analysis else [])})
        )
        ctx.update({
            "source_code": _read_source(project_path, rel_path),
            "imports": imports,
            "symbols": symbols_list,
        })
    elif task_type == "symbol":
        sym_dumped = symbol or None
        sym_source = ""
        if sym_dumped:
            sym_source = (
                Path(str(_project_root(project_path) / rel_path)).read_text(
                    encoding="utf-8", errors="replace"
                )
            )
        ctx.update({
            "symbol_id": symbol.id if symbol else "",
            "symbol_name": symbol.name if symbol else "",
            "symbol_type": symbol.symbol_type if symbol else "",
            "signature": symbol.signature if symbol and symbol.signature else "",
            "docstring": symbol.docstring if symbol and symbol.docstring else "",
            "parent_class": "",
            "source_code": sym_source,
            "called_functions": "",
            "calling_functions": "",
        })
    elif task_type == "equation":
        full_source = _read_source(project_path, rel_path)
        expr = equation.expression if equation else ""
        ctx.update({
            "equation_id": equation.id if equation else "",
            "equation_name": equation.name if equation and equation.name else "",
            "containing_function": "",
            "containing_class": "",
            "expression": expr,
            "surrounding_code": full_source,
            "variables_in_scope": "",
        })

    try:
        user_prompt = analyzer.format_prompt(prompt_name, **ctx)
    except Exception as exc:
        user_prompt = f"[prompt formatting failed: {exc}]\nAnalyze the source at {rel_path}."

    schema_class = analyzer.get_output_schema(prompt_name)
    json_schema = _pydantic_json_schema(schema_class)

    return GetNextAnalysisTaskOutput(
        task_id=task_id,
        task_type=task_type,
        file_path=None if file_record is None else file_record.path,
        target_name=(symbol.name if task_type == "symbol" and symbol else
                     equation.name if task_type == "equation" and equation else None),
        system_prompt=template.system_prompt,
        user_prompt=user_prompt,
        output_schema_name=template.output_schema,
        output_schema=json_schema,
        has_more=True,
    )


async def register_memory_tools(server: Server) -> None:
    """Register all memory-related tools."""

    @server.tool()
    async def project_bootstrap(input: BootstrapInput) -> BootstrapOutput:
        """
        Initialize a new project memory directory.
        Creates .project-memory/ with config.yaml, project_knowledge.db, and initial state.
        """
        from project_memory_mcp.workflows.index_repository import index_repository

        config = {
            "mode": input.mode,
            "use_vector_similarity": input.use_vector_similarity,
        }

        await index_repository(input.project_path, config)

        return BootstrapOutput(
            created=True,
            memory_dir=".project-memory",
            next_step="project.get_next_analysis_task",
        )

    @server.tool()
    async def project_plan_indexing(input: PlanIndexingInput) -> PlanIndexingOutput:
        """
        List the steps for building the knowledge graph.
        Returns the execution plan for the agent to follow.
        """
        from project_memory_mcp.static_analysis.file_scanner import (
            FileScanner,
        )

        scanner = FileScanner(input.project_path)
        file_infos = scanner.scan()

        return PlanIndexingOutput(
            steps=[
                "scan_files (create File records + extract static structure)",
                "analyze_files_with_llm: loop get_next_analysis_task(task_type='file')"
                " then submit_file_analysis until no more tasks",
                "analyze_symbols_with_llm: repeat for task_type='symbol'",
                "analyze_equations_with_llm: repeat for task_type='equation'",
                "build_graph_edges",
                "generate_manual",
            ],
            estimated_files=len(file_infos),
            excluded_paths=[],
        )

    @server.tool()
    async def project_scan_files(input: ScanFilesInput) -> ScanFilesOutput:
        """
        Scan the project for source files and create initial File records in the database.
        """
        from project_memory_mcp.workflows.index_repository import IndexRepositoryWorkflow

        workflow = IndexRepositoryWorkflow(input.project_path)
        workflow.exclude_patterns = set(input.exclude_patterns)
        file_infos = workflow.scanner.scan()

        # Process files (create File records)
        processed = 0
        skipped = []
        for file_info in file_infos:
            try:
                await workflow._process_file(file_info, {"files_indexed": 0})
                processed += 1
            except Exception as e:
                skipped.append(f"{file_info.relative_path}: {e}")

        return ScanFilesOutput(
            files_found=len(file_infos),
            files_inserted=processed,
            skipped=skipped,
        )

    @server.tool()
    async def project_get_next_analysis_task(input: GetNextAnalysisTaskInput) -> GetNextAnalysisTaskOutput:
        """
        Get the next analysis task for the agent to execute.
        Returns a task with the prompt template and required output schema.

        Agent-driven mode: the MCP server does NOT call any LLM. It instead returns
        the fully formatted system + user prompt and the JSON Schema the agent must
        produce. The external agent reads the prompt, analyzes the source code, and
        submits the structured result via project_submit_*_analysis.
        """
        from sqlalchemy import or_, select

        from project_memory_mcp.db.connection import get_session
        from project_memory_mcp.db.models import (
            AnalysisStatus,
            Equation,
            File,
            LLMAnalysisRecord,
            Symbol,
        )
        from project_memory_mcp.llm_analysis.analyzer import get_analyzer

        analyzer = get_analyzer(mode="agent_driven")

        async with get_session() as session:
            if input.task_type == "file":
                # Find next source file that still needs LLM analysis.
                # The source of truth for "needs analysis" is llm_analysis_records
                # (status == PENDING), mirroring the symbol/equation branches and the
                # background analysis loop. Relying solely on files.analysis_status led
                # to desync: a file could be COMPLETED in llm_analysis_records while
                # files.analysis_status was still PENDING (or vice-versa), causing the
                # agent to receive an already-completed file repeatedly. Also exclude
                # archive paths so stale `_archive` files don't get surfaced as tasks.
                stmt = (
                    select(File)
                    .join(LLMAnalysisRecord, (
                        (LLMAnalysisRecord.target_type == "file")
                        & (LLMAnalysisRecord.target_id == File.id)
                    ))
                    .where(
                        File.is_source.is_(True)
                        & (LLMAnalysisRecord.status == AnalysisStatus.PENDING.value)
                        & ~or_(
                            File.path.like("%/_archive/%"),
                            File.path.like("%\\_archive\\%"),
                        )
                    )
                    .order_by(File.id)
                    .limit(1)
                )
                result = await session.execute(stmt)
                file_record = result.scalar_one_or_none()

                if file_record:
                    return _build_analysis_task_output(
                        analyzer=analyzer,
                        task_type="file",
                        task_id=f"file_{file_record.id}",
                        file_record=file_record,
                        project_path=input.project_path,
                    )

            elif input.task_type == "symbol":
                stmt = (
                    select(Symbol)
                    .join(File, File.id == Symbol.file_id)
                    .where(Symbol.symbol_type.in_(["function", "method", "class"]))
                    .where(
                        ~or_(
                            File.path.like("%/_archive/%"),
                            File.path.like("%\\_archive\\%"),
                        )
                    )
                    .outerjoin(
                        LLMAnalysisRecord,
                        (LLMAnalysisRecord.target_type == "symbol") &
                        (LLMAnalysisRecord.target_id == Symbol.id),
                    )
                    .where(
                        (LLMAnalysisRecord.id.is_(None))
                        | (LLMAnalysisRecord.status == AnalysisStatus.PENDING.value)
                    )
                    .order_by(Symbol.id)
                    .limit(1)
                )
                result = await session.execute(stmt)
                symbol = result.scalar_one_or_none()

                if symbol:
                    # Load parent file for language + path
                    file_stmt = select(File).where(File.id == symbol.file_id)
                    file_record = (await session.execute(file_stmt)).scalar_one_or_none()
                    return _build_analysis_task_output(
                        analyzer=analyzer,
                        task_type="symbol",
                        task_id=f"symbol_{symbol.id}",
                        file_record=file_record,
                        symbol=symbol,
                        project_path=input.project_path,
                    )

            elif input.task_type == "equation":
                stmt = (
                    select(Equation)
                    .join(File, File.id == Equation.file_id)
                    .where(
                        ~or_(
                            File.path.like("%/_archive/%"),
                            File.path.like("%\\_archive\\%"),
                        )
                    )
                    .outerjoin(
                        LLMAnalysisRecord,
                        (LLMAnalysisRecord.target_type == "equation") &
                        (LLMAnalysisRecord.target_id == Equation.id),
                    )
                    .where(
                        (LLMAnalysisRecord.id.is_(None))
                        | (LLMAnalysisRecord.status == AnalysisStatus.PENDING.value)
                    )
                    .order_by(Equation.id)
                    .limit(1)
                )
                result = await session.execute(stmt)
                equation = result.scalar_one_or_none()

                if equation:
                    file_stmt = select(File).where(File.id == equation.file_id)
                    file_record = (await session.execute(file_stmt)).scalar_one_or_none()
                    return _build_analysis_task_output(
                        analyzer=analyzer,
                        task_type="equation",
                        task_id=f"equation_{equation.id}",
                        file_record=file_record,
                        equation=equation,
                        project_path=input.project_path,
                    )

        return GetNextAnalysisTaskOutput(
            task_id="",
            task_type="none",
            has_more=False,
        )

    @server.tool()
    async def project_submit_file_analysis(input: SubmitFileAnalysisInput) -> SubmitFileAnalysisOutput:
        """
        Submit file analysis result from agent.
        Validates and stores the analysis in the database.
        """
        from sqlalchemy import select

        from project_memory_mcp.db.connection import get_session
        from project_memory_mcp.db.models import AnalysisStatus, File, LLMAnalysisRecord
        from project_memory_mcp.llm_analysis.analyzer import get_analyzer

        analyzer = get_analyzer(mode="agent_driven")

        # Validate result
        validated = analyzer.validate_agent_result(
            task_id=input.task_id,
            output_schema="FileAnalysisResult",
            agent_response=input.analysis,
        )

        if validated.status != AnalysisStatus.COMPLETED:
            return SubmitFileAnalysisOutput(
                accepted=False,
                db_updated=False,
                next_step="project_get_next_analysis_task",
                error=validated.error,
                reason=validated.error or "analysis validation failed",
            )

        # Store in database
        async with get_session() as session:
            stmt = select(File).where(File.id == int(input.task_id.split("_")[-1]))
            result = await session.execute(stmt)
            file_record = result.scalar_one_or_none()

            if file_record:
                file_record.purpose = validated.result.get("purpose", "")
                file_record.llm_summary = validated.result.get("summary", "")
                file_record.llm_confidence = validated.result.get("confidence", 0.0)
                file_record.is_core = validated.result.get("is_core", False)
                import json as _json
                file_record.key_concepts = _json.dumps(
                    validated.result.get("key_concepts", []), ensure_ascii=False
                )
                file_record.risk_notes = _json.dumps(
                    validated.result.get("risk_notes", []), ensure_ascii=False
                )
                file_record.analysis_status = AnalysisStatus.COMPLETED.value

                # Update LLM analysis record
                stmt = select(LLMAnalysisRecord).where(
                    (LLMAnalysisRecord.target_type == "file") &
                    (LLMAnalysisRecord.target_id == file_record.id)
                )
                result = await session.execute(stmt)
                analysis_record = result.scalar_one_or_none()

                if analysis_record:
                    analysis_record.output_json = str(validated.result)
                    analysis_record.confidence = validated.confidence
                    analysis_record.status = AnalysisStatus.COMPLETED.value

                return SubmitFileAnalysisOutput(
                    accepted=True,
                    db_updated=True,
                    next_step="project_get_next_analysis_task",
                )

            return SubmitFileAnalysisOutput(
                accepted=False,
                db_updated=False,
                next_step="project_get_next_analysis_task",
                error=f"file record not found for task_id {input.task_id}",
                reason=f"file record not found for task_id {input.task_id}",
            )

    @server.tool()
    async def project_submit_symbol_analysis(input: SubmitSymbolAnalysisInput) -> SubmitSymbolAnalysisOutput:
        """
        Submit symbol analysis result from agent.
        """
        from sqlalchemy import select

        from project_memory_mcp.db.connection import get_session
        from project_memory_mcp.db.models import AnalysisStatus, LLMAnalysisRecord, Symbol
        from project_memory_mcp.llm_analysis.analyzer import get_analyzer

        analyzer = get_analyzer(mode="agent_driven")

        validated = analyzer.validate_agent_result(
            task_id=input.task_id,
            output_schema="SymbolAnalysisResult",
            agent_response=input.analysis,
        )

        if validated.status != AnalysisStatus.COMPLETED:
            return SubmitSymbolAnalysisOutput(
                accepted=False,
                db_updated=False,
                next_step="project_get_next_analysis_task",
                error=validated.error,
                reason=validated.error or "analysis validation failed",
            )

        async with get_session() as session:
            symbol_id = int(input.task_id.split("_")[-1])
            stmt = select(Symbol).where(Symbol.id == symbol_id)
            result = await session.execute(stmt)
            symbol = result.scalar_one_or_none()

            if symbol:
                symbol.llm_summary = validated.result.get("responsibility", "")
                symbol.responsibility = validated.result.get("responsibility", "")
                symbol.side_effects = str(validated.result.get("side_effects", []))
                symbol.confidence = validated.result.get("confidence", 0.0)

                # Update analysis record
                stmt = select(LLMAnalysisRecord).where(
                    (LLMAnalysisRecord.target_type == "symbol") &
                    (LLMAnalysisRecord.target_id == symbol_id)
                )
                result = await session.execute(stmt)
                analysis_record = result.scalar_one_or_none()

                if analysis_record:
                    analysis_record.output_json = str(validated.result)
                    analysis_record.confidence = validated.confidence
                    analysis_record.status = AnalysisStatus.COMPLETED.value

                return SubmitSymbolAnalysisOutput(
                    accepted=True,
                    db_updated=True,
                    next_step="project_get_next_analysis_task",
                )

            return SubmitSymbolAnalysisOutput(
                accepted=False,
                db_updated=False,
                next_step="project_get_next_analysis_task",
                error=f"symbol record not found for task_id {input.task_id}",
                reason=f"symbol record not found for task_id {input.task_id}",
            )

    @server.tool()
    async def project_submit_equation_analysis(input: SubmitEquationAnalysisInput) -> SubmitEquationAnalysisOutput:
        """
        Submit equation analysis result from agent.
        """
        import json

        from sqlalchemy import select

        from project_memory_mcp.db.connection import get_session
        from project_memory_mcp.db.models import AnalysisStatus, Equation, LLMAnalysisRecord
        from project_memory_mcp.llm_analysis.analyzer import get_analyzer

        analyzer = get_analyzer(mode="agent_driven")

        validated = analyzer.validate_agent_result(
            task_id=input.task_id,
            output_schema="EquationAnalysisResult",
            agent_response=input.analysis,
        )

        if validated.status != AnalysisStatus.COMPLETED:
            return SubmitEquationAnalysisOutput(
                accepted=False,
                db_updated=False,
                next_step="project_get_next_analysis_task",
                error=validated.error,
                reason=validated.error or "analysis validation failed",
            )

        async with get_session() as session:
            eq_id = int(input.task_id.split("_")[-1])
            stmt = select(Equation).where(Equation.id == eq_id)
            result = await session.execute(stmt)
            equation = result.scalar_one_or_none()

            if equation:
                equation.name = validated.result.get("name", equation.name)
                equation.equation_type = validated.result.get("equation_type", "unknown")
                equation.mathematical_meaning = validated.result.get("mathematical_meaning", "")
                equation.physical_meaning = validated.result.get("physical_meaning")
                equation.algorithmic_role = validated.result.get("algorithmic_role", "")
                equation.inputs_json = json.dumps(validated.result.get("inputs", []))
                equation.outputs_json = json.dumps(validated.result.get("outputs", []))
                equation.intermediate_variables_json = json.dumps(validated.result.get("intermediate_variables", []))
                equation.constants_json = json.dumps(validated.result.get("constants", []))
                equation.units_json = json.dumps(validated.result.get("units", {}))
                equation.assumptions = str(validated.result.get("assumptions", []))
                equation.confidence = validated.result.get("confidence", 0.0)

                # Update analysis record
                stmt = select(LLMAnalysisRecord).where(
                    (LLMAnalysisRecord.target_type == "equation") &
                    (LLMAnalysisRecord.target_id == eq_id)
                )
                result = await session.execute(stmt)
                analysis_record = result.scalar_one_or_none()

                if analysis_record:
                    analysis_record.output_json = str(validated.result)
                    analysis_record.confidence = validated.confidence
                    analysis_record.status = AnalysisStatus.COMPLETED.value

                return SubmitEquationAnalysisOutput(
                    accepted=True,
                    db_updated=True,
                    next_step="project_get_next_analysis_task",
                )

            return SubmitEquationAnalysisOutput(
                accepted=False,
                db_updated=False,
                next_step="project_get_next_analysis_task",
                error=f"equation record not found for task_id {input.task_id}",
                reason=f"equation record not found for task_id {input.task_id}",
            )

    @server.tool()
    async def project_build_graph_edges(input: BuildGraphEdgesInput) -> BuildGraphEdgesOutput:
        """
        Build graph edges from static analysis and LLM analysis results.
        """
        from project_memory_mcp.workflows.index_repository import IndexRepositoryWorkflow

        workflow = IndexRepositoryWorkflow(input.project_path)
        await workflow._build_graph_edges()

        return BuildGraphEdgesOutput(
            edges_created=0,  # Would be actual count
            low_confidence_edges=[],
            unresolved_edges=[],
        )

    @server.tool()
    async def project_rescan_changed_files(input: RescanChangedFilesInput) -> RescanChangedFilesOutput:
        """
        Rescan only changed files based on hash comparison.
        """
        from project_memory_mcp.workflows.rescan_changed_files import rescan_changed_files

        result = await rescan_changed_files(input.project_path)

        return RescanChangedFilesOutput(
            files_checked=result.get("files_checked", 0),
            files_changed=result.get("files_changed", 0),
            files_added=result.get("files_added", 0),
            files_deleted=result.get("files_deleted", 0),
        )

    @server.tool()
    async def project_generate_manual(input: GenerateManualInput) -> GenerateManualOutput:
        """
        Generate or update PROJECT_AGENT_MANUAL.md for the project.
        """
        from project_memory_mcp.workflows.generate_manual import GenerateManualWorkflow

        workflow = GenerateManualWorkflow(input.project_path)
        await workflow.execute()

        return GenerateManualOutput(
            generated=True,
            manual_path=".project-memory/PROJECT_AGENT_MANUAL.md",
            sections=0,
        )

    @server.tool()
    async def project_start_analysis_loop(input: StartAnalysisLoopInput) -> StartAnalysisLoopOutput:
        """
        Start the LLM analysis loop in the background to automatically build Descriptions/Summaries.
        """
        from project_memory_mcp.utils.config import get_settings, reset_settings
        from project_memory_mcp.llm_analysis.analyzer import _analyzer
        import project_memory_mcp.llm_analysis.analyzer as analyzer_mod
        from project_memory_mcp.workflows.background_analysis import runner

        # Reset global settings/analyzer
        reset_settings()
        settings = get_settings()

        # Apply custom configuration or defaults
        settings.llm_provider = input.llm_provider if input.llm_provider is not None else "myself"
        settings.llm_api_base = input.llm_api_base if input.llm_api_base is not None else "http://localhost:4000/v1"
        settings.llm_model = input.llm_model if input.llm_model is not None else "patcher-main"
        settings.llm_api_key = input.llm_api_key if input.llm_api_key is not None else "not-needed"
        settings.llm_mode = "server_driven"

        # Re-initialize analyzer
        analyzer_mod._analyzer = None

        # Start background loop
        msg = runner.start(input.project_path)
        return StartAnalysisLoopOutput(started=runner.is_running, message=msg)

    @server.tool()
    async def project_get_analysis_progress(input: GetAnalysisProgressInput) -> GetAnalysisProgressOutput:
        """
        Check the progress and status of the background analysis loop.
        """
        from sqlalchemy import select, func
        from project_memory_mcp.db.connection import get_session
        from project_memory_mcp.db.models import LLMAnalysisRecord, AnalysisStatus
        from project_memory_mcp.workflows.background_analysis import runner

        total_tasks = 0
        pending_tasks = 0
        completed_tasks = 0
        failed_tasks = 0

        async with get_session() as session:
            # Query counts
            stmt_total = select(func.count()).select_from(LLMAnalysisRecord)
            total_tasks = (await session.execute(stmt_total)).scalar() or 0

            stmt_pending = select(func.count()).select_from(LLMAnalysisRecord).where(LLMAnalysisRecord.status == AnalysisStatus.PENDING.value)
            pending_tasks = (await session.execute(stmt_pending)).scalar() or 0

            stmt_completed = select(func.count()).select_from(LLMAnalysisRecord).where(LLMAnalysisRecord.status == AnalysisStatus.COMPLETED.value)
            completed_tasks = (await session.execute(stmt_completed)).scalar() or 0

            stmt_failed = select(func.count()).select_from(LLMAnalysisRecord).where(LLMAnalysisRecord.status == AnalysisStatus.FAILED.value)
            failed_tasks = (await session.execute(stmt_failed)).scalar() or 0

        return GetAnalysisProgressOutput(
            is_running=runner.is_running,
            current_task_id=runner.current_task_id,
            last_error=runner.last_error,
            total_tasks=total_tasks,
            pending_tasks=pending_tasks,
            completed_tasks=completed_tasks,
            failed_tasks=failed_tasks,
        )

