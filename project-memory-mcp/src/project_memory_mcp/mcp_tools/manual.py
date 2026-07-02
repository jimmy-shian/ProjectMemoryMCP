"""Manual tools for the Project Memory MCP server."""


from mcp.server import Server
from pydantic import BaseModel, Field


class GenerateManualInput(BaseModel):
    project_path: str = Field(default=".", description="Path to the project root")


class GenerateManualOutput(BaseModel):
    generated: bool
    manual_path: str
    sections: int
    content: str


async def register_manual_tools(server: Server) -> None:
    """Register manual generation tools."""

    @server.tool()
    async def project_generate_manual(input: GenerateManualInput) -> GenerateManualOutput:
        """
        Generate PROJECT_AGENT_MANUAL.md for the project.
        """
        from project_memory_mcp.workflows.generate_manual import GenerateManualWorkflow

        workflow = GenerateManualWorkflow(input.project_path)
        result = await workflow.execute()

        return GenerateManualOutput(
            generated=True,
            manual_path=".project-memory/PROJECT_AGENT_MANUAL.md",
            sections=result.get("sections", 0),
            content=result.get("content", ""),
        )
