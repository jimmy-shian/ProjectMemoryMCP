"""Workflow for applying edits."""

import os
from typing import Any

from project_memory_mcp.db.connection import get_session
from project_memory_mcp.db.models import OperationsHistory
from project_memory_mcp.utils.hashing import calculate_file_hash


class ApplyEditWorkflow:
    """
    Workflow for applying confirmed edits and updating the knowledge graph.
    """

    def __init__(self, project_path: str, config: dict[str, Any] | None = None):
        self.project_path = project_path
        self.config = config or {}

    async def apply_edit(
        self,
        file_path: str,
        changes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Apply an edit to a file and update the database.
        """
        full_path = os.path.join(self.project_path, file_path)

        # Read current content
        try:
            with open(full_path, encoding="utf-8") as f:
                current_content = f.read()
        except FileNotFoundError:
            return {"success": False, "error": "File not found"}

        # Apply changes
        proposed_content = self._apply_changes(current_content, changes)

        # Write file
        try:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(proposed_content)
        except Exception as e:
            return {"success": False, "error": f"Failed to write file: {e}"}

        # Update database
        await self._update_database(file_path, current_content, proposed_content)

        # Return updated entities that need rescanning
        return {
            "success": True,
            "file_path": file_path,
            "updated_entities": [file_path],
        }

    def _apply_changes(self, content: str, changes: list[dict[str, Any]]) -> str:
        """Apply a list of changes to content."""
        lines = content.splitlines(keepends=True)

        for change in changes:
            change_type = change.get("type", "replace")

            if change_type == "replace":
                start = change.get("start_line", 1) - 1
                end = change.get("end_line", start + 1)
                new_content = change.get("new_content", "")
                new_lines = new_content.splitlines(keepends=True)
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

    async def _update_database(
        self,
        file_path: str,
        old_content: str,
        new_content: str,
    ) -> None:
        """Update database with new file content and hash."""
        from project_memory_mcp.static_analysis.file_scanner import FileScanner
        from project_memory_mcp.workflows.rescan_changed_files import RescanChangedFilesWorkflow

        # Trigger rescan for this file
        scanner = FileScanner(self.project_path)
        file_info = scanner.get_file_info(file_path)

        if file_info:
            # This will update the file record and re-extract structure
            rescan_workflow = RescanChangedFilesWorkflow(self.project_path)
            # We just need to process this one file
            pass  # Simplified for now

        # Record operation
        async with get_session() as session:
            record = OperationsHistory(
                operation_type="edit",
                target_type="file",
                target_name=file_path,
                affected_files_json=f'["{file_path}"]',
                before_hashes_json=f'{{"{file_path}": "{calculate_file_hash(full_path=os.path.join(self.project_path, file_path), content=old_content)}"}}',
                after_hashes_json=f'{{"{file_path}": "{calculate_file_hash(full_path=os.path.join(self.project_path, file_path), content=new_content)}"}}',
                status="completed",
            )
            session.add(record)
