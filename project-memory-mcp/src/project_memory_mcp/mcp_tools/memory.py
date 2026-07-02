"""Memory tools for the Project Memory MCP server."""

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
    required_output_schema: dict[str, Any]


class SubmitFileAnalysisInput(BaseModel):
    task_id: str
    file_path: str
    analysis: dict[str, Any]


class SubmitFileAnalysisOutput(BaseModel):
    accepted: bool
    db_updated: bool
    next_step: str


class SubmitSymbolAnalysisInput(BaseModel):
    task_id: str
    symbol_name: str
    analysis: dict[str, Any]


class SubmitSymbolAnalysisOutput(BaseModel):
    accepted: bool
    db_updated: bool
    next_step: str


class SubmitEquationAnalysisInput(BaseModel):
    task_id: str
    equation_name: str
    analysis: dict[str, Any]


class SubmitEquationAnalysisOutput(BaseModel):
    accepted: bool
    db_updated: bool
    next_step: str


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

        result = await index_repository(input.project_path, config)

        return BootstrapOutput(
            created=True,
            memory_dir=".project-memory",
            next_step="project.plan_indexing",
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
                "scan_files",
                "extract_static_structure",
                "analyze_files_with_llm",
                "analyze_symbols_with_llm",
                "analyze_equations_with_llm",
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
        """
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

        analyzer = get_analyzer(mode="agent_driven")

        async with get_session() as session:
            if input.task_type == "file":
                # Find next file that needs analysis
                stmt = select(File).where(
                    (File.is_source == True) &
                    (File.analysis_status == AnalysisStatus.PENDING.value)
                ).limit(1)
                result = await session.execute(stmt)
                file_record = result.scalar_one_or_none()

                if file_record:
                    task = analyzer.create_analysis_task(
                        task_id=f"file_{file_record.id}",
                        task_type="file",
                        target_path=file_record.path,
                        context={"file_id": file_record.id},
                    )
                    return GetNextAnalysisTaskOutput(
                        task_id=task["task_id"],
                        task_type=task["task_type"],
                        file_path=file_record.path,
                        required_output_schema={"type": "object"},  # Would be actual JSON schema
                    )

            elif input.task_type == "symbol":
                stmt = select(Symbol).where(
                    Symbol.symbol_type.in_(["function", "method", "class"])
                ).join(LLMAnalysisRecord, isouter=True).where(
                    LLMAnalysisRecord.id.is_(None)
                ).limit(1)
                result = await session.execute(stmt)
                symbol = result.scalar_one_or_none()

                if symbol:
                    task = analyzer.create_analysis_task(
                        task_id=f"symbol_{symbol.id}",
                        task_type="symbol",
                        target_path=symbol.qualified_name,
                        target_name=symbol.name,
                        context={"symbol_id": symbol.id, "file_id": symbol.file_id},
                    )
                    return GetNextAnalysisTaskOutput(
                        task_id=task["task_id"],
                        task_type=task["task_type"],
                        file_path=None,
                        target_name=symbol.name,
                        required_output_schema={"type": "object"},
                    )

            elif input.task_type == "equation":
                stmt = select(Equation).join(LLMAnalysisRecord, isouter=True).where(
                    LLMAnalysisRecord.id.is_(None)
                ).limit(1)
                result = await session.execute(stmt)
                equation = result.scalar_one_or_none()

                if equation:
                    task = analyzer.create_analysis_task(
                        task_id=f"equation_{equation.id}",
                        task_type="equation",
                        target_path=equation.name or f"eq_{equation.id}",
                        target_name=equation.name,
                        context={"equation_id": equation.id, "file_id": equation.file_id},
                    )
                    return GetNextAnalysisTaskOutput(
                        task_id=task["task_id"],
                        task_type=task["task_type"],
                        file_path=None,
                        target_name=equation.name,
                        required_output_schema={"type": "object"},
                    )

        return GetNextAnalysisTaskOutput(
            task_id="",
            task_type="none",
            required_output_schema={},
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
