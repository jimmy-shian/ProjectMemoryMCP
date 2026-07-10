import asyncio
import os
import sys
import unittest
from pathlib import Path
from datetime import datetime

# Add project src to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Force DB_PATH environment variable for testing
TEST_DB_PATH = Path(__file__).resolve().parent.parent / "test_knowledge_submission_dedup.db"
os.environ["DB_PATH"] = str(TEST_DB_PATH)

from sqlalchemy import select
from project_memory_mcp.db.connection import init_db, get_session, close_db
from project_memory_mcp.db.models import (
    Base,
    AnalysisStatus,
    Equation,
    File,
    LLMAnalysisRecord,
    Symbol,
)
from project_memory_mcp.server import create_server


class TestTaskSubmissionDeduplication(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        # Initialize test DB
        await init_db(db_path=str(TEST_DB_PATH))
        from project_memory_mcp.db.connection import get_engine
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        # Create server instance
        self.server = await create_server()

    async def asyncTearDown(self):
        await close_db()
        if TEST_DB_PATH.exists():
            try:
                TEST_DB_PATH.unlink()
            except Exception:
                pass

    async def test_symbol_submission_deduplication(self):
        """Test that submitting a symbol without an existing LLMAnalysisRecord creates one and completes it."""
        # 1. Add file and symbol to DB, leaving LLMAnalysisRecord empty
        # Use an actually existing file relative to project root
        async with get_session() as session:
            file_rec = File(
                path="tests/test_all.py",
                filename="test_all.py",
                extension=".py",
                language="python",
                file_type="source",
                size_bytes=1000,
                hash="dummy_hash_router",
                last_modified=datetime.utcnow(),
                is_source=True,
            )
            session.add(file_rec)
            await session.flush()

            symbol_rec = Symbol(
                file_id=file_rec.id,
                name="resolve_generation_route",
                qualified_name="backend.generation.routing.router.resolve_generation_route",
                symbol_type="function",
                start_line=10,
                end_line=50,
            )
            session.add(symbol_rec)
            await session.flush()
            
            # Note down symbol ID
            symbol_id = symbol_rec.id

        # 2. Get next task via tool. Since there is no LLMAnalysisRecord, it should return this symbol.
        task_output_res = await self.server.call_tool(
            "project_get_next_analysis_task",
            arguments={"input": {"task_type": "symbol", "project_path": "."}}
        )
        self.assertTrue(len(task_output_res) > 0 and len(task_output_res[0]) > 0)
        
        # We can decode the response to make sure it's the expected task
        import json
        task_data = json.loads(task_output_res[0][0].text)
        self.assertEqual(task_data["task_id"], f"symbol_{symbol_id}")
        self.assertEqual(task_data["task_type"], "symbol")
        self.assertTrue(task_data["has_more"])

        # 3. Submit symbol analysis. This symbol has NO record in LLMAnalysisRecord.
        # Submit tool should accept and dynamically create LLMAnalysisRecord.
        submit_res = await self.server.call_tool(
            "project_submit_symbol_analysis",
            arguments={
                "input": {
                    "task_id": f"symbol_{symbol_id}",
                    "symbol_name": "resolve_generation_route",
                    "analysis": {
                        "responsibility": "Resolves generation routes based on config",
                        "confidence": 0.95
                    }
                }
            }
        )
        submit_data = json.loads(submit_res[0][0].text)
        self.assertTrue(submit_data["accepted"])
        self.assertTrue(submit_data["db_updated"])

        # 4. Verify that LLMAnalysisRecord was indeed created and set to COMPLETED
        async with get_session() as session:
            stmt = select(LLMAnalysisRecord).where(
                (LLMAnalysisRecord.target_type == "symbol") &
                (LLMAnalysisRecord.target_id == symbol_id)
            )
            record = (await session.execute(stmt)).scalar_one_or_none()
            self.assertIsNotNone(record)
            self.assertEqual(record.status, AnalysisStatus.COMPLETED.value)
            self.assertEqual(record.confidence, 0.95)

        # 5. Get next task again. It should return has_more=False or none task because the symbol is completed.
        task_output_res_2 = await self.server.call_tool(
            "project_get_next_analysis_task",
            arguments={"input": {"task_type": "symbol", "project_path": "."}}
        )
        task_data_2 = json.loads(task_output_res_2[0][0].text)
        self.assertFalse(task_data_2["has_more"])
        self.assertEqual(task_data_2["task_id"], "")

    async def test_equation_submission_deduplication(self):
        """Test that submitting an equation without an existing LLMAnalysisRecord creates one and completes it."""
        async with get_session() as session:
            file_rec = File(
                path="tests/test_all.py",
                filename="test_all.py",
                extension=".py",
                language="python",
                file_type="source",
                size_bytes=1000,
                hash="dummy_hash_router",
                last_modified=datetime.utcnow(),
                is_source=True,
            )
            session.add(file_rec)
            await session.flush()

            eq_rec = Equation(
                file_id=file_rec.id,
                name="router_cost_formula",
                expression="cost = latency * weight",
                start_line=20,
                end_line=20,
            )
            session.add(eq_rec)
            await session.flush()
            eq_id = eq_rec.id

        # 1. Get next task. It should return the equation.
        task_output_res = await self.server.call_tool(
            "project_get_next_analysis_task",
            arguments={"input": {"task_type": "equation", "project_path": "."}}
        )
        import json
        task_data = json.loads(task_output_res[0][0].text)
        self.assertEqual(task_data["task_id"], f"equation_{eq_id}")

        # 2. Submit equation analysis
        submit_res = await self.server.call_tool(
            "project_submit_equation_analysis",
            arguments={
                "input": {
                    "task_id": f"equation_{eq_id}",
                    "equation_name": "router_cost_formula",
                    "analysis": {
                        "mathematical_meaning": "Latency multiplied by cost weight",
                        "algorithmic_role": "Calculates total path selection cost",
                        "confidence": 0.9,
                        "evidence": "cost = latency * weight"
                    }
                }
            }
        )
        submit_data = json.loads(submit_res[0][0].text)
        self.assertTrue(submit_data["accepted"])

        # 3. Verify DB record
        async with get_session() as session:
            stmt = select(LLMAnalysisRecord).where(
                (LLMAnalysisRecord.target_type == "equation") &
                (LLMAnalysisRecord.target_id == eq_id)
            )
            record = (await session.execute(stmt)).scalar_one_or_none()
            self.assertIsNotNone(record)
            self.assertEqual(record.status, AnalysisStatus.COMPLETED.value)

        # 4. Get next task again. Should be empty.
        task_output_res_2 = await self.server.call_tool(
            "project_get_next_analysis_task",
            arguments={"input": {"task_type": "equation", "project_path": "."}}
        )
        task_data_2 = json.loads(task_output_res_2[0][0].text)
        self.assertFalse(task_data_2["has_more"])

    async def test_file_submission_deduplication_fallback(self):
        """Test that submitting a file without an existing LLMAnalysisRecord creates one and completes it."""
        async with get_session() as session:
            file_rec = File(
                path="tests/test_all.py",
                filename="test_all.py",
                extension=".py",
                language="python",
                file_type="source",
                size_bytes=1000,
                hash="dummy_hash_router",
                last_modified=datetime.utcnow(),
                is_source=True,
            )
            session.add(file_rec)
            await session.flush()
            file_id = file_rec.id

        # Submit file analysis
        import json
        submit_res = await self.server.call_tool(
            "project_submit_file_analysis",
            arguments={
                "input": {
                    "task_id": f"file_{file_id}",
                    "file_path": "tests/test_all.py",
                    "analysis": {
                        "summary": "This file contains route routing logic",
                        "confidence": 0.88
                    }
                }
            }
        )
        submit_data = json.loads(submit_res[0][0].text)
        self.assertTrue(submit_data["accepted"])

        # Verify DB record
        async with get_session() as session:
            stmt = select(LLMAnalysisRecord).where(
                (LLMAnalysisRecord.target_type == "file") &
                (LLMAnalysisRecord.target_id == file_id)
            )
            record = (await session.execute(stmt)).scalar_one_or_none()
            self.assertIsNotNone(record)
            self.assertEqual(record.status, AnalysisStatus.COMPLETED.value)



if __name__ == "__main__":
    unittest.main()
