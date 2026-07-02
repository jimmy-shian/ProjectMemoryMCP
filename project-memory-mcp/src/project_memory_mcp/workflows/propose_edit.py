"""Workflow for proposing edits."""

from typing import Any

from project_memory_mcp.utils.hashing import calculate_file_hash


class ProposeEditWorkflow:
    """
    Workflow for proposing edits without executing them.
    """

    def __init__(self, project_path: str, config: dict[str, Any] | None = None):
        self.project_path = project_path
        self.config = config or {}

    async def propose_edit(
        self,
        file_path: str,
        changes: list[dict[str, Any]],
        reason: str,
        impact_analysis: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Create an edit proposal with impact analysis.
        """
        # Read current file
        full_path = f"{self.project_path}/{file_path}"
        try:
            with open(full_path, encoding="utf-8") as f:
                current_content = f.read()
        except FileNotFoundError:
            return {"success": False, "error": "File not found"}

        # Generate proposed content
        proposed_content = self._apply_changes(current_content, changes)

        # Generate diff
        diff = self._generate_diff(current_content, proposed_content)

        plan = {
            "file_path": file_path,
            "current_hash": calculate_file_hash(full_path),
            "proposed_hash": calculate_file_hash(full_path, proposed_content),
            "changes": changes,
            "reason": reason,
            "diff": diff,
            "impact_analysis": impact_analysis,
        }

        return {"success": True, "plan": plan}

    def _apply_changes(self, content: str, changes: list[dict[str, Any]]) -> str:
        """Apply a list of changes to content."""
        lines = content.splitlines(keepends=True)

        for change in changes:
            change_type = change.get("type", "replace")

            if change_type == "replace":
                start = change.get("start_line", 1) - 1
                end = change.get("end_line", start + 1)
                new_lines = change.get("new_content", "").splitlines(keepends=True)
                lines[start:end] = new_lines

            elif change_type == "insert":
                line = change.get("line", 1) - 1
                new_content = change.get("content", "")
                lines.insert(line, new_content + "\n")

            elif change_type == "delete":
                start = change.get("start_line", 1) - 1
                end = change.get("end_line", start + 1)
                lines[start:end] = []

        return "".join(lines)

    def _generate_diff(self, old: str, new: str) -> str:
        """Generate a unified diff."""
        import difflib
        old_lines = old.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)
        diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=""))
        return "\n".join(diff)


async def propose_edit(
    project_path: str,
    file_path: str,
    changes: list[dict[str, Any]],
    reason: str,
    impact_analysis: dict[str, Any],
) -> dict[str, Any]:
    workflow = ProposeEditWorkflow(project_path)
    return await workflow.propose_edit(file_path, changes, reason, impact_analysis)
