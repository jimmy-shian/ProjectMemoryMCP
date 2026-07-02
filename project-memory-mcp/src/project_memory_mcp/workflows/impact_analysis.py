"""Workflow for impact analysis before edits."""

from typing import Any, Dict, List, Optional

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from project_memory_mcp.db.connection import get_session
from project_memory_mcp.db.models import (
    Equation, File, GraphEdge, OperationsHistory, Symbol,
)
from project_memory_mcp.llm_analysis.analyzer import get_analyzer
from project_memory_mcp.llm_analysis.schemas import ImpactAnalysisResult, RiskLevel

MAX_TRAVERSAL_DEPTH = 3


class ImpactAnalysisWorkflow:
    """
    Workflow for analyzing the impact of a proposed change.

    Uses graph traversal to find affected entities, then uses LLM
    to assess risk and provide recommendations.
    """

    def __init__(self, project_path: str, config: dict[str, Any] | None = None):
        self.project_path = project_path
        self.config = config or {}
        self.analyzer = get_analyzer(mode="agent_driven")

    async def analyze_impact(
        self,
        target_type: str,  # file, symbol, equation
        target_name: str,
        target_path: str,
        operation_type: str = "modify",  # modify, delete, refactor
        max_depth: int = 3,
    ) -> Dict[str, Any]:
        """
        Perform impact analysis for a proposed change.

        Returns:
            Dictionary with impact analysis results
        """
        # Step 1: Find target entity in database
        target_info = await self._find_target(target_type, target_name, target_path)
        if not target_info:
            return {
                "success": False,
                "error": f"Target not found: {target_type} {target_name} at {target_path}",
            }

        # Step 2: Traverse graph to find affected entities
        affected = await self._traverse_impact_graph(
            target_info["type"],
            target_info["id"],
            max_depth,
        )

        # Step 3: Get related test files
        test_files = await self._find_related_tests(affected)

        # Step 4: Create LLM analysis task for detailed impact assessment
        task = self.analyzer.create_analysis_task(
            task_id=f"impact_{target_type}_{target_name}",
            task_type="impact_analysis",
            target_path=target_path,
            target_name=target_name,
            context={
                "target_type": target_type,
                "target_name": target_name,
                "target_path": target_path,
                "operation_type": operation_type,
                "dependencies": json.dumps(affected["direct"], indent=2),
                "transitive_dependencies": json.dumps(affected["transitive"], indent=2),
                "test_files": json.dumps(test_files, indent=2),
            },
        )

        # Step 5: Return task for agent to execute
        return {
            "success": True,
            "target": target_info,
            "affected": affected,
            "test_files": test_files,
            "analysis_task": task,
            "next_step": "Submit analysis result via project.submit_impact_analysis",
        }

    async def _find_target(
        self,
        target_type: str,
        target_name: str,
        target_path: str,
    ) -> Optional[Dict[str, Any]]:
        """Find the target entity in the database."""
        from sqlalchemy import select
        async with get_session() as session:
            if target_type == "file":
                stmt = select(File).where(File.path == target_path)
                result = await session.execute(stmt)
                file_record = result.scalar_one_or_none()
                if file_record:
                    return {"type": "file", "id": file_record.id, "record": file_record}

            elif target_type == "symbol":
                stmt = select(Symbol).where(
                    (Symbol.name == target_name) |
                    (Symbol.qualified_name == target_path)
                )
                result = await session.execute(stmt)
                symbol = result.scalar_one_or_none()
                if symbol:
                    return {"type": "symbol", "id": symbol.id, "record": symbol}

            elif target_type == "equation":
                stmt = select(Equation).where(
                    (Equation.name == target_name) |
                    (Equation.name == target_path)
                )
                result = await session.execute(stmt)
                equation = result.scalar_one_or_none()
                if equation:
                    return {"type": "equation", "id": equation.id, "record": equation}

        return None

    async def _traverse_impact_graph(
        self,
        source_type: str,
        source_id: int,
        max_depth: int,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Traverse the graph to find all affected entities.

        Uses BFS to find entities that depend on the target.
        """
        from sqlalchemy import select

        affected = {
            "direct": [],
            "transitive": [],
        }

        visited: Set[str] = set()
        queue = [(source_type, source_id, 0)]

        async with get_session() as session:
            while queue:
                current_type, current_id, depth = queue.pop(0)

                if depth > max_depth:
                    continue

                key = f"{current_type}:{current_id}"
                if key in visited:
                    continue
                visited.add(key)

                # Find incoming edges (things that depend on this)
                stmt = select(GraphEdge).where(
                    (GraphEdge.target_type == current_type) &
                    (GraphEdge.target_id == current_id) &
                    (GraphEdge.edge_type.in_(["CALLS", "USES", "DEPENDS_ON", "IMPORTS", "READS", "WRITES", "MODIFIES"]))
                )
                result = await session.execute(stmt)
                edges = result.scalars().all()

                for edge in edges:
                    dep_info = await self._get_entity_info(
                        session,
                        edge.source_type,
                        edge.source_id,
                    )
                    if dep_info:
                        dep_entry = {
                            "type": edge.source_type,
                            "id": edge.source_id,
                            "name": dep_info.get("name"),
                            "path": dep_info.get("path"),
                            "edge_type": edge.edge_type,
                            "depth": depth + 1,
                        }

                        if depth == 0:
                            affected["direct"].append(dep_entry)
                        else:
                            affected["transitive"].append(dep_entry)

                        # Continue traversal
                        queue.append((edge.source_type, edge.source_id, depth + 1))

        return affected

    async def _get_entity_info(
        self,
        session,
        entity_type: str,
        entity_id: int,
    ) -> Optional[Dict[str, Any]]:
        """Get basic info about an entity."""
        from sqlalchemy import select

        if entity_type == "file":
            stmt = select(File).where(File.id == entity_id)
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            if record:
                return {"name": record.filename, "path": record.path}

        elif entity_type == "symbol":
            stmt = select(Symbol).where(Symbol.id == entity_id)
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            if record:
                return {"name": record.name, "path": record.qualified_name}

        elif entity_type == "equation":
            stmt = select(Equation).where(Equation.id == entity_id)
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            if record:
                return {"name": record.name, "path": f"{record.file_id}:{record.start_line}"}

        return None

    async def _find_related_tests(self, affected: Dict[str, List[Dict[str, Any]]]) -> List[str]:
        """Find test files related to affected entities."""
        from sqlalchemy import select

        test_files = set()
        all_affected = affected["direct"] + affected["transitive"]

        async with get_session() as session:
            for entity in all_affected:
                if entity["type"] == "file":
                    # Find test files that import this file
                    stmt = select(GraphEdge).where(
                        (GraphEdge.source_type == "file") &
                        (GraphEdge.target_type == "file") &
                        (GraphEdge.target_id == entity["id"]) &
                        (GraphEdge.edge_type == "IMPORTS")
                    )
                    result = await session.execute(stmt)
                    edges = result.scalars().all()

                    for edge in edges:
                        source_file = await self._get_entity_info(session, "file", edge.source_id)
                        if source_file and source_file.get("path", "").startswith("test"):
                            test_files.add(source_file["path"])

                elif entity["type"] == "symbol":
                    # Find test files that call this symbol
                    stmt = select(GraphEdge).where(
                        (GraphEdge.source_type == "file") &
                        (GraphEdge.target_type == "symbol") &
                        (GraphEdge.target_id == entity["id"]) &
                        (GraphEdge.edge_type == "CALLS")
                    )
                    result = await session.execute(stmt)
                    edges = result.scalars().all()

                    for edge in edges:
                        source_file = await self._get_entity_info(session, "file", edge.source_id)
                        if source_file and source_file.get("path", "").startswith("test"):
                            test_files.add(source_file["path"])

        return list(test_files)

    async def submit_impact_analysis(self, task_id: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Submit the impact analysis result from agent."""
        from project_memory_mcp.llm_analysis.schemas import AnalysisStatus

        # Validate and store
        validated = self.analyzer.validate_agent_result(
            task_id=task_id,
            output_schema="ImpactAnalysisResult",
            agent_response=analysis,
        )

        # Store in database
        from sqlalchemy import select, update
        async with get_session() as session:
            stmt = select(OperationsHistory).where(OperationsHistory.id == int(task_id.split("_")[-1]) if "_" in task_id else -1)
            # Just create a new record
            record = OperationsHistory(
                operation_type="impact_analysis",
                target_type=validated.task_type,
                target_name=validated.target_name,
                affected_files_json=json.dumps(validated.result.get("affected_files", [])),
                affected_symbols_json=json.dumps(validated.result.get("affected_symbols", [])),
                affected_equations_json=json.dumps(validated.result.get("affected_equations", [])),
                impact_summary=validated.result.get("risk_summary", ""),
                risk_level=validated.result.get("risk_level", "low"),
                status="completed",
            )
            session.add(record)

        return {
            "success": True,
            "analysis": validated.result,
        }


async def query_impact(
    target_type: str,
    target_name: str,
    target_path: str,
    operation_type: str = "modify",
    max_depth: int = 3,
) -> Dict[str, Any]:
    """Convenience function to run impact analysis."""
    workflow = ImpactAnalysisWorkflow(".")
    return await workflow.analyze_impact(target_type, target_name, target_path, operation_type, max_depth)