"""Workflow for delete safety analysis."""

import json
from typing import Any

from project_memory_mcp.db.connection import get_session
from project_memory_mcp.db.models import Equation, File, GraphEdge, OperationsHistory, Symbol
from project_memory_mcp.llm_analysis.analyzer import get_analyzer


class DeleteSafetyWorkflow:
    """
    Workflow for analyzing the safety of deleting a file, symbol, or equation.

    Features:
    - Finds all references to the target
    - Finds all dependents
    - Identifies orphaned code
    - Provides delete safety assessment via LLM
    - Requires explicit confirmation before actual deletion
    """

    def __init__(self, project_path: str, config: dict[str, Any] | None = None):
        self.project_path = project_path
        self.config = config or {}
        self.analyzer = get_analyzer(mode="agent_driven")

    async def analyze_delete_safety(
        self,
        target_type: str,  # file, symbol, equation
        target_name: str,
        target_path: str,
    ) -> dict[str, Any]:
        """
        Analyze the safety of deleting a target.

        Returns:
            Dictionary with delete safety analysis - NEVER deletes automatically
        """
        # Step 1: Find target
        target_info = await self._find_target(target_type, target_name, target_path)
        if not target_info:
            return {
                "success": False,
                "error": f"Target not found: {target_type} {target_name}",
            }

        # Step 2: Find all references
        references = await self._find_references(target_info["type"], target_info["id"])

        # Step 3: Find all dependents
        dependents = await self._find_dependents(target_info["type"], target_info["id"])

        # Step 4: Identify orphaned code
        orphans = await self._find_orphaned_code(references, dependents)

        # Step 5: Create LLM analysis task
        task = self.analyzer.create_analysis_task(
            task_id=f"delete_safety_{target_type}_{target_name}",
            task_type="delete_safety",
            target_path=target_path,
            target_name=target_name,
            context={
                "target_type": target_type,
                "target_name": target_name,
                "target_path": target_path,
                "references": json.dumps(references, indent=2),
                "dependents": json.dumps(dependents, indent=2),
                "orphaned_code": json.dumps(orphans, indent=2),
            },
        )

        return {
            "success": True,
            "target": target_info,
            "references": references,
            "dependents": dependents,
            "orphaned_code": orphans,
            "can_delete": len(references) == 0 and len(dependents) == 0,
            "analysis_task": task,
            "next_step": "Submit delete safety analysis via project.submit_delete_safety",
            "warning": "DELETION NOT PERFORMED. Must call project.confirm_delete with explicit confirmation.",
        }

    async def confirm_delete(
        self,
        target_type: str,
        target_name: str,
        target_path: str,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        """
        Confirm and execute deletion (only with explicit confirmation).

        Returns:
            Dictionary indicating success or failure
        """
        if not confirmed:
            return {
                "success": False,
                "message": "Deletion not confirmed. Pass confirmed=True if you are sure.",
            }

        # Find target
        target_info = await self._find_target(target_type, target_name, target_path)
        if not target_info:
            return {
                "success": False,
                "error": "Target not found",
            }

        # Execute deletion
        from sqlalchemy import delete

        target_type_actual = target_info["type"]
        target_id = target_info["id"]

        async with get_session() as session:
            # Delete related data first
            if target_type_actual == "file":
                from sqlalchemy import select

                from project_memory_mcp.db.models import Equation, Symbol

                # Delete graph edges involving this file
                await session.execute(
                    delete(GraphEdge).where(
                        (GraphEdge.source_type == "file") & (GraphEdge.source_id == target_id) |
                        (GraphEdge.target_type == "file") & (GraphEdge.target_id == target_id)
                    )
                )

                # Delete actual file record (cascade handles symbols, equations, variables)
                file_stmt = select(File).where(File.id == target_id)
                file_result = await session.execute(file_stmt)
                file_record = file_result.scalar_one_or_none()
                if file_record:
                    await session.delete(file_record)

            elif target_type_actual == "symbol":
                # Delete edges involving this symbol
                await session.execute(
                    delete(GraphEdge).where(
                        (GraphEdge.source_type == "symbol") & (GraphEdge.source_id == target_id) |
                        (GraphEdge.target_type == "symbol") & (GraphEdge.target_id == target_id)
                    )
                )

                symbol_stmt = select(Symbol).where(Symbol.id == target_id)
                symbol_result = await session.execute(symbol_stmt)
                symbol_record = symbol_result.scalar_one_or_none()
                if symbol_record:
                    await session.delete(symbol_record)

            elif target_type_actual == "equation":
                eq_stmt = select(Equation).where(Equation.id == target_id)
                eq_result = await session.execute(eq_stmt)
                eq_record = eq_result.scalar_one_or_none()
                if eq_record:
                    await session.delete(eq_record)

            # Record operation
            record = OperationsHistory(
                operation_type="delete",
                target_type=target_type_actual,
                target_name=target_name,
                impact_summary=f"Deleted {target_type_actual}: {target_name}",
                status="completed",
            )
            session.add(record)

        return {
            "success": True,
            "message": f"Deleted {target_type_actual}: {target_name}",
        }

    async def _find_target(
        self,
        target_type: str,
        target_name: str,
        target_path: str,
    ) -> dict[str, Any] | None:
        """Find target entity."""
        from sqlalchemy import select

        async with get_session() as session:
            if target_type == "file":
                stmt = select(File).where(File.path == target_path)
                result = await session.execute(stmt)
                record = result.scalar_one_or_none()
                if record:
                    return {"type": "file", "id": record.id, "record": record}

            elif target_type == "symbol":
                stmt = select(Symbol).where(
                    (Symbol.name == target_name) |
                    (Symbol.qualified_name == target_path)
                )
                result = await session.execute(stmt)
                record = result.scalar_one_or_none()
                if record:
                    return {"type": "symbol", "id": record.id, "record": record}

            elif target_type == "equation":
                stmt = select(Equation).where(
                    Equation.name == target_name
                )
                result = await session.execute(stmt)
                record = result.scalar_one_or_none()
                if record:
                    return {"type": "equation", "id": record.id, "record": record}

        return None

    async def _find_references(
        self,
        target_type: str,
        target_id: int,
    ) -> list[dict[str, Any]]:
        """Find all references to the target."""
        from sqlalchemy import select
        async with get_session() as session:
            stmt = select(GraphEdge).where(
                (GraphEdge.target_type == target_type) &
                (GraphEdge.target_id == target_id) &
                (GraphEdge.edge_type.in_(["IMPORTS", "CALLS", "USES", "READS", "DEPENDS_ON"]))
            )
            result = await session.execute(stmt)
            edges = result.scalars().all()

            references = []
            for edge in edges:
                ref = {
                    "source_type": edge.source_type,
                    "source_id": edge.source_id,
                    "edge_type": edge.edge_type,
                    "description": edge.description,
                }
                references.append(ref)

            return references

    async def _find_dependents(
        self,
        target_type: str,
        target_id: int,
    ) -> list[dict[str, Any]]:
        """Find all dependents of the target."""
        from sqlalchemy import select
        async with get_session() as session:
            stmt = select(GraphEdge).where(
                (GraphEdge.source_type == target_type) &
                (GraphEdge.source_id == target_id)
            )
            result = await session.execute(stmt)
            edges = result.scalars().all()

            dependents = []
            for edge in edges:
                dep = {
                    "target_type": edge.target_type,
                    "target_id": edge.target_id,
                    "edge_type": edge.edge_type,
                    "description": edge.description,
                }
                dependents.append(dep)

            return dependents

    async def _find_orphaned_code(
        self,
        references: list[dict[str, Any]],
        dependents: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Identify code that would become orphaned if target is deleted."""
        orphans = []

        # Code that references the target but doesn't reference anything else
        for ref in references:
            if ref["source_id"] not in {d["source_id"] for d in dependents}:
                orphans.append(ref)

        return orphans


async def analyze_delete_safety(
    target_type: str,
    target_name: str,
    target_path: str,
) -> dict[str, Any]:
    """Convenience function for delete safety analysis."""
    workflow = DeleteSafetyWorkflow(".")
    return await workflow.analyze_delete_safety(target_type, target_name, target_path)
