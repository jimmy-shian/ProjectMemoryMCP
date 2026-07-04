"""Query tools for the Project Memory MCP server."""

from typing import Any

from mcp.server import Server
from pydantic import BaseModel, Field


class SearchFilesInput(BaseModel):
    project_path: str = Field(default=".", description="Path to the project root")
    query: str = Field(
        ...,
        description="Keyword query; matched against filename, purpose, llm_summary, key_concepts",
    )
    only_analyzed: bool = Field(
        default=False,
        description="If true, only return files whose LLM analysis is completed",
    )
    limit: int = Field(default=20, description="Max number of files to return")


class SearchFilesOutput(BaseModel):
    query: str
    total: int
    files: list[dict[str, Any]]


class QueryFileInput(BaseModel):
    project_path: str = Field(default=".", description="Path to the project root")
    file_path: str = Field(..., description="Path to the file to query")


class QueryFileOutput(BaseModel):
    found: bool
    file_info: dict[str, Any] | None = None
    symbols: list[dict[str, Any]] = []
    equations: list[dict[str, Any]] = []
    dependencies: list[dict[str, Any]] = []


class QuerySymbolInput(BaseModel):
    project_path: str = Field(default=".", description="Path to the project root")
    symbol_name: str = Field(..., description="Name of the symbol to query")
    qualified_name: str | None = Field(None, description="Qualified name if known")


class QuerySymbolOutput(BaseModel):
    found: bool
    symbol_info: dict[str, Any] | None = None
    callers: list[dict[str, Any]] = []
    callees: list[dict[str, Any]] = []
    equations: list[dict[str, Any]] = []
    impact: dict[str, Any] | None = None


class QueryEquationInput(BaseModel):
    project_path: str = Field(default=".", description="Path to the project root")
    keyword: str = Field(..., description="Keyword to search for in equations")
    equation_name: str | None = Field(None, description="Specific equation name")


class QueryEquationOutput(BaseModel):
    found: bool
    equations: list[dict[str, Any]] = []
    variables: list[dict[str, Any]] = []
    related_symbols: list[dict[str, Any]] = []


class QueryImpactInput(BaseModel):
    project_path: str = Field(default=".", description="Path to the project root")
    target_type: str = Field(..., description="Type: file, symbol, equation")
    target_name: str = Field(..., description="Name of the target")
    operation_type: str = Field(default="modify", description="Operation: modify, delete, refactor")


class QueryImpactOutput(BaseModel):
    success: bool
    affected_files: list[str] = []
    affected_symbols: list[str] = []
    affected_equations: list[str] = []
    risk_level: str = "low"
    risk_summary: str = ""
    suggested_tests: list[str] = []
    suggested_order: list[str] = []


async def register_query_tools(server: Server) -> None:
    """Register all query tools."""

    @server.tool()
    async def project_search_files(input: SearchFilesInput) -> SearchFilesOutput:
        """
        Search indexed files by description / keyword.
        Matches the query against filename, purpose, and llm_summary (the
        description produced by the external agent during indexing). Files that
        have been analyzed by the agent (llm_summary present) are ranked first,
        so callers can quickly bring up the correct, fully-described file data.

        Use this after init→index→agent summarization to find files by what they
        do rather than by exact path.
        """
        from sqlalchemy import or_, select

        from project_memory_mcp.db.connection import get_session
        from project_memory_mcp.db.models import AnalysisStatus, File

        like = f"%{input.query}%"
        conditions = [
            or_(
                File.filename.ilike(like),
                File.path.ilike(like),
                File.purpose.ilike(like),
                File.llm_summary.ilike(like),
                File.key_concepts.ilike(like),
                File.risk_notes.ilike(like),
            )
        ]
        if input.only_analyzed:
            conditions.append(File.analysis_status == AnalysisStatus.COMPLETED.value)

        async with get_session() as session:
            stmt = select(File).where(*conditions).limit(input.limit)
            result = await session.execute(stmt)
            files = result.scalars().all()

            # Sort: analyzed-with-summary first, then by has summary, then path
            def _rank(f: File) -> tuple[int, str]:
                if f.analysis_status == AnalysisStatus.COMPLETED.value and f.llm_summary:
                    return (0, f.path)
                if f.llm_summary:
                    return (1, f.path)
                return (2, f.path)

            ordered = sorted(files, key=_rank)

            return SearchFilesOutput(
                query=input.query,
                total=len(ordered),
                files=[{
                    "path": f.path,
                    "language": f.language,
                    "purpose": f.purpose,
                    "llm_summary": f.llm_summary,
                    "is_core": f.is_core,
                    "is_entrypoint": f.is_entrypoint,
                    "is_source": f.is_source,
                    "analysis_status": f.analysis_status,
                    "llm_confidence": f.llm_confidence,
                } for f in ordered],
            )

    @server.tool()
    async def project_query_file(input: QueryFileInput) -> QueryFileOutput:
        """
        Query a file for its purpose, symbols, equations, and dependencies.
        """
        from sqlalchemy import select

        from project_memory_mcp.db.connection import get_session
        from project_memory_mcp.db.models import Equation, File, GraphEdge, Symbol

        async with get_session() as session:
            stmt = select(File).where(File.path == input.file_path)
            result = await session.execute(stmt)
            file_record = result.scalar_one_or_none()

            if not file_record:
                return QueryFileOutput(found=False)

            # Get symbols
            stmt = select(Symbol).where(Symbol.file_id == file_record.id)
            result = await session.execute(stmt)
            symbols = result.scalars().all()

            # Get equations
            stmt = select(Equation).where(Equation.file_id == file_record.id)
            result = await session.execute(stmt)
            equations = result.scalars().all()

            # Get dependencies (imports)
            stmt = select(GraphEdge).where(
                (GraphEdge.source_type == "file") &
                (GraphEdge.source_id == file_record.id) &
                (GraphEdge.edge_type == "IMPORTS")
            )
            result = await session.execute(stmt)
            dep_edges = result.scalars().all()

            dependencies = []
            for edge in dep_edges:
                if edge.target_type == "file":
                    stmt = select(File).where(File.id == edge.target_id)
                    result = await session.execute(stmt)
                    target_file = result.scalar_one_or_none()
                    if target_file:
                        dependencies.append({
                            "path": target_file.path,
                            "type": "import",
                        })

            return QueryFileOutput(
                found=True,
                file_info={
                    "path": file_record.path,
                    "language": file_record.language,
                    "purpose": file_record.purpose,
                    "llm_summary": file_record.llm_summary,
                    "key_concepts": file_record.key_concepts,
                    "risk_notes": file_record.risk_notes,
                    "llm_confidence": file_record.llm_confidence,
                    "is_core": file_record.is_core,
                    "is_entrypoint": file_record.is_entrypoint,
                    "analysis_status": file_record.analysis_status,
                },
                symbols=[{
                    "name": s.name,
                    "qualified_name": s.qualified_name,
                    "type": s.symbol_type,
                    "start_line": s.start_line,
                    "end_line": s.end_line,
                    "responsibility": s.responsibility,
                } for s in symbols],
                equations=[{
                    "name": e.name,
                    "type": e.equation_type,
                    "expression": e.expression,
                    "start_line": e.start_line,
                    "mathematical_meaning": e.mathematical_meaning,
                } for e in equations],
                dependencies=dependencies,
            )

    @server.tool()
    async def project_query_symbol(input: QuerySymbolInput) -> QuerySymbolOutput:
        """
        Query a symbol (function, class, method) for its definition, callers, callees.
        """
        from sqlalchemy import or_, select

        from project_memory_mcp.db.connection import get_session
        from project_memory_mcp.db.models import Equation, GraphEdge, Symbol

        async with get_session() as session:
            # Find symbol
            conditions = [Symbol.name == input.symbol_name]
            if input.qualified_name:
                conditions.append(Symbol.qualified_name == input.qualified_name)
            stmt = select(Symbol).where(or_(*conditions))
            result = await session.execute(stmt)
            symbol = result.scalar_one_or_none()

            if not symbol:
                return QuerySymbolOutput(found=False)

            # Get callers (incoming CALLS edges)
            stmt = select(GraphEdge).where(
                (GraphEdge.target_type == "symbol") &
                (GraphEdge.target_id == symbol.id) &
                (GraphEdge.edge_type == "CALLS")
            )
            result = await session.execute(stmt)
            caller_edges = result.scalars().all()

            callers = []
            for edge in caller_edges:
                stmt = select(Symbol).where(Symbol.id == edge.source_id)
                result = await session.execute(stmt)
                caller = result.scalar_one_or_none()
                if caller:
                    callers.append({
                        "name": caller.name,
                        "qualified_name": caller.qualified_name,
                        "file_path": caller.file_id,  # Would need to join
                    })

            # Get callees (outgoing CALLS edges)
            stmt = select(GraphEdge).where(
                (GraphEdge.source_type == "symbol") &
                (GraphEdge.source_id == symbol.id) &
                (GraphEdge.edge_type == "CALLS")
            )
            result = await session.execute(stmt)
            callee_edges = result.scalars().all()

            callees = []
            for edge in callee_edges:
                stmt = select(Symbol).where(Symbol.id == edge.target_id)
                result = await session.execute(stmt)
                callee = result.scalar_one_or_none()
                if callee:
                    callees.append({
                        "name": callee.name,
                        "qualified_name": callee.qualified_name,
                    })

            # Get equations used by this symbol
            stmt = select(GraphEdge).where(
                (GraphEdge.source_type == "symbol") &
                (GraphEdge.source_id == symbol.id) &
                (GraphEdge.edge_type == "USES_EQUATION")
            )
            result = await session.execute(stmt)
            eq_edges = result.scalars().all()

            equations = []
            for edge in eq_edges:
                stmt = select(Equation).where(Equation.id == edge.target_id)
                result = await session.execute(stmt)
                eq = result.scalar_one_or_none()
                if eq:
                    equations.append({
                        "name": eq.name,
                        "type": eq.equation_type,
                        "expression": eq.expression,
                    })

            return QuerySymbolOutput(
                found=True,
                symbol_info={
                    "name": symbol.name,
                    "qualified_name": symbol.qualified_name,
                    "type": symbol.symbol_type,
                    "start_line": symbol.start_line,
                    "end_line": symbol.end_line,
                    "signature": symbol.signature,
                    "docstring": symbol.docstring,
                    "responsibility": symbol.responsibility,
                    "side_effects": symbol.side_effects,
                    "confidence": symbol.confidence,
                },
                callers=callers,
                callees=callees,
                equations=equations,
            )

    @server.tool()
    async def project_query_equation(input: QueryEquationInput) -> QueryEquationOutput:
        """
        Query equations by keyword or name.
        """
        from sqlalchemy import or_, select

        from project_memory_mcp.db.connection import get_session
        from project_memory_mcp.db.models import Equation, GraphEdge, Symbol, Variable

        async with get_session() as session:
            # Search by keyword
            if input.equation_name:
                stmt = select(Equation).where(
                    or_(
                        Equation.name == input.equation_name,
                        Equation.expression.contains(input.keyword),
                    )
                )
            else:
                stmt = select(Equation).where(
                    Equation.expression.contains(input.keyword)
                )
            result = await session.execute(stmt)
            equations = result.scalars().all()

            if not equations:
                return QueryEquationOutput(found=False)

            eq_list = []
            all_variables = []
            all_symbols = []

            for eq in equations:
                # Get variables
                stmt = select(Variable).where(Variable.symbol_id.in_(
                    select(Equation.symbol_id).where(Equation.id == eq.id)
                ))
                result = await session.execute(stmt)
                variables = result.scalars().all()

                for v in variables:
                    all_variables.append({
                        "name": v.name,
                        "role": v.role,
                        "unit": v.unit,
                        "shape": v.shape,
                    })

                # Get related symbols
                stmt = select(GraphEdge).where(
                    (GraphEdge.target_type == "equation") &
                    (GraphEdge.target_id == eq.id)
                )
                result = await session.execute(stmt)
                sym_edges = result.scalars().all()

                for edge in sym_edges:
                    if edge.source_type == "symbol":
                        stmt = select(Symbol).where(Symbol.id == edge.source_id)
                        result = await session.execute(stmt)
                        sym = result.scalar_one_or_none()
                        if sym:
                            all_symbols.append({
                                "name": sym.name,
                                "qualified_name": sym.qualified_name,
                                "type": sym.symbol_type,
                            })

                eq_list.append({
                    "id": eq.id,
                    "name": eq.name,
                    "type": eq.equation_type,
                    "expression": eq.expression,
                    "normalized_expression": eq.normalized_expression,
                    "start_line": eq.start_line,
                    "end_line": eq.end_line,
                    "mathematical_meaning": eq.mathematical_meaning,
                    "physical_meaning": eq.physical_meaning,
                    "algorithmic_role": eq.algorithmic_role,
                    "inputs": eq.inputs_json,
                    "outputs": eq.outputs_json,
                    "intermediate_variables": eq.intermediate_variables_json,
                    "constants": eq.constants_json,
                    "units": eq.units_json,
                    "assumptions": eq.assumptions,
                    "confidence": eq.confidence,
                })

            return QueryEquationOutput(
                found=True,
                equations=eq_list,
                variables=all_variables,
                related_symbols=all_symbols,
            )

    @server.tool()
    async def project_query_impact(input: QueryImpactInput) -> QueryImpactOutput:
        """
        Analyze the impact of modifying/deleting a target.
        """
        from project_memory_mcp.workflows.impact_analysis import ImpactAnalysisWorkflow

        workflow = ImpactAnalysisWorkflow(input.project_path)
        result = await workflow.analyze_impact(
            target_type=input.target_type,
            target_name=input.target_name,
            target_path=input.target_name,  # Would need proper path
            operation_type=input.operation_type,
        )

        if not result.get("success"):
            return QueryImpactOutput(
                success=False,
                risk_summary=result.get("error", "Unknown error"),
            )

        affected = result.get("affected", {})
        return QueryImpactOutput(
            success=True,
            affected_files=[a.get("path", "") for a in affected.get("direct", []) if a.get("type") == "file"],
            affected_symbols=[a.get("name", "") for a in affected.get("direct", []) if a.get("type") == "symbol"],
            affected_equations=[a.get("name", "") for a in affected.get("direct", []) if a.get("type") == "equation"],
            risk_level="medium",  # Would come from LLM analysis
            risk_summary="Impact analysis created. Submit analysis via project.submit_impact_analysis for detailed risk assessment.",
            suggested_tests=result.get("test_files", []),
            suggested_order=[],
        )
