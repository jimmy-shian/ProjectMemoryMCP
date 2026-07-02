"""Edit tools for the Project Memory MCP server."""

from typing import Any

from mcp.server import Server
from pydantic import BaseModel, Field


class ProposeEditInput(BaseModel):
    project_path: str = Field(default=".", description="Path to the project root")
    file_path: str = Field(..., description="Path to the file to edit")
    changes: list[dict[str, Any]] = Field(..., description="List of changes to propose")
    reason: str = Field(..., description="Reason for the edit")


class ProposeEditOutput(BaseModel):
    proposed: bool
    edit_plan: list[dict[str, Any]]
    impact_analysis: dict[str, Any]
    requires_confirmation: bool


class ApplyEditInput(BaseModel):
    project_path: str = Field(default=".", description="Path to the project root")
    file_path: str = Field(..., description="Path to the file to edit")
    changes: list[dict[str, Any]] = Field(..., description="List of changes to apply")
    confirm: bool = Field(default=False, description="Confirm the edit")


class ApplyEditOutput(BaseModel):
    applied: bool
    file_path: str
    updated_entities: list[str]
    rescan_needed: bool


class DeleteCandidateInput(BaseModel):
    project_path: str = Field(default=".", description="Path to the project root")
    target_type: str = Field(..., description="Type: file, symbol, equation")
    target_name: str = Field(..., description="Name of target")
    target_path: str = Field(..., description="Path to target")


class DeleteCandidateOutput(BaseModel):
    can_delete: bool
    risk_level: str
    references: list[dict[str, Any]]
    dependents: list[dict[str, Any]]
    orphaned_code: list[dict[str, Any]]
    recommendation: str
    requires_confirmation: bool


class ConfirmDeleteInput(BaseModel):
    project_path: str = Field(default=".", description="Path to the project root")
    target_type: str = Field(..., description="Type: file, symbol, equation")
    target_name: str = Field(..., description="Name of target")
    target_path: str = Field(..., description="Path to target")
    confirmed: bool = Field(default=False, description="Explicit confirmation")


class ConfirmDeleteOutput(BaseModel):
    deleted: bool
    message: str


async def register_edit_tools(server: Server) -> None:
    """Register all edit-related tools."""

    @server.tool()
    async def project_propose_edit(input: ProposeEditInput) -> ProposeEditOutput:
        """
        Propose an edit plan without executing it.
        Performs impact analysis and returns the plan for review.
        """
        from project_memory_mcp.workflows.impact_analysis import ImpactAnalysisWorkflow
        from project_memory_mcp.workflows.propose_edit import ProposeEditWorkflow

        # First do impact analysis
        impact_workflow = ImpactAnalysisWorkflow(input.project_path)
        impact_result = await impact_workflow.analyze_impact(
            target_type="file",
            target_name=input.file_path,
            target_path=input.file_path,
            operation_type="modify",
        )

        # Then create edit proposal
        edit_workflow = ProposeEditWorkflow(input.project_path)
        proposal = await edit_workflow.propose_edit(
            file_path=input.file_path,
            changes=input.changes,
            reason=input.reason,
            impact_analysis=impact_result,
        )

        return ProposeEditOutput(
            proposed=True,
            edit_plan=proposal.get("plan", []),
            impact_analysis=impact_result,
            requires_confirmation=True,
        )

    @server.tool()
    async def project_apply_edit(input: ApplyEditInput) -> ApplyEditOutput:
        """
        Apply a confirmed edit to a file and update the knowledge graph.
        """
        if not input.confirm:
            return ApplyEditOutput(
                applied=False,
                file_path=input.file_path,
                updated_entities=[],
                rescan_needed=False,
            )

        from project_memory_mcp.workflows.apply_edit import ApplyEditWorkflow

        workflow = ApplyEditWorkflow(input.project_path)
        result = await workflow.apply_edit(
            file_path=input.file_path,
            changes=input.changes,
        )

        return ApplyEditOutput(
            applied=result.get("success", False),
            file_path=input.file_path,
            updated_entities=result.get("updated_entities", []),
            rescan_needed=True,
        )

    @server.tool()
    async def project_delete_candidate(input: DeleteCandidateInput) -> DeleteCandidateOutput:
        """
        Analyze whether a file/symbol/equation can be safely deleted.
        Does NOT perform deletion - only analysis.
        """
        from project_memory_mcp.workflows.delete_safety import DeleteSafetyWorkflow

        workflow = DeleteSafetyWorkflow(input.project_path)
        result = await workflow.analyze_delete_safety(
            target_type=input.target_type,
            target_name=input.target_name,
            target_path=input.target_path,
        )

        return DeleteCandidateOutput(
            can_delete=result.get("can_delete", False),
            risk_level="low" if result.get("can_delete") else "high",
            references=result.get("references", []),
            dependents=result.get("dependents", []),
            orphaned_code=result.get("orphaned_code", []),
            recommendation=result.get("recommendation", "Do not delete"),
            requires_confirmation=not result.get("can_delete", False),
        )

    @server.tool()
    async def project_confirm_delete(input: ConfirmDeleteInput) -> ConfirmDeleteOutput:
        """
        Confirm and execute deletion of a file/symbol/equation.
        Requires explicit confirmation.
        """
        if not input.confirmed:
            return ConfirmDeleteOutput(
                deleted=False,
                message="Deletion not confirmed. Set confirmed=true to proceed.",
            )

        from project_memory_mcp.workflows.delete_safety import DeleteSafetyWorkflow

        workflow = DeleteSafetyWorkflow(input.project_path)
        result = await workflow.confirm_delete(
            target_type=input.target_type,
            target_name=input.target_name,
            target_path=input.target_path,
            confirmed=True,
        )

        return ConfirmDeleteOutput(
            deleted=result.get("success", False),
            message=result.get("message", ""),
        )
