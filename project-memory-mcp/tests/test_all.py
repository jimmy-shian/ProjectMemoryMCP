import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path
from datetime import datetime

# Add project src to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Force env var for sqlite path in memory or custom test db path
TEST_DB_PATH = Path(__file__).resolve().parent.parent / "test_knowledge.db"
os.environ["DB_PATH"] = str(TEST_DB_PATH)

from sqlalchemy import select
from project_memory_mcp.utils.config import get_settings, reset_settings, load_config
from project_memory_mcp.db.connection import init_db, get_session, close_db
from project_memory_mcp.db.models import (
    Base,
    AnalysisStatus,
    Equation,
    File,
    LLMAnalysisRecord,
    Symbol,
    GraphEdge,
)
from project_memory_mcp.llm_analysis.analyzer import get_analyzer
from project_memory_mcp.llm_analysis.schemas import (
    FileAnalysisResult,
    SymbolAnalysisResult,
    EquationAnalysisResult,
)
from project_memory_mcp.workflows.background_analysis import runner, BackgroundAnalysisRunner
from project_memory_mcp.static_analysis.static_locator import StaticLocator
from project_memory_mcp.workflows.generate_manual import GenerateManualWorkflow


class TestProjectMemoryFullSuite(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        await init_db(db_path=str(TEST_DB_PATH))
        from project_memory_mcp.db.connection import get_engine
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        await close_db()


    def test_config_loading(self):
        """Test configuration loading and settings parsing."""
        reset_settings()
        settings = get_settings()
        self.assertIsNotNone(settings.exclude_patterns)
        self.assertEqual(settings.llm_mode, "agent_driven")

    def test_static_locator_parsing(self):
        """Test tree-sitter static locator with a simple python code snippet."""
        locator = StaticLocator()
        # Create a temp python file to parse
        temp_file = Path(__file__).parent / "temp_dummy.py"
        try:
            temp_file.write_text(
                "import os\n"
                "def calculate_val(x):\n"
                "    # loss = x ** 2\n"
                "    return x * x\n",
                encoding="utf-8"
            )
            analysis = locator.analyze_file(str(temp_file))
            self.assertEqual(analysis.language, "python")
            # Verify functions found
            func_names = [f.name for f in analysis.functions]
            self.assertIn("calculate_val", func_names)
        finally:
            if temp_file.exists():
                temp_file.unlink()

    async def test_manual_generation(self):
        """Test workflow for manual generation (PROJECT_AGENT_MANUAL.md)."""
        async with get_session() as session:
            file_rec = File(
                path="src/dummy_main.py",
                filename="dummy_main.py",
                extension=".py",
                language="python",
                file_type="source",
                size_bytes=200,
                hash="hash_main",
                last_modified=datetime.utcnow(),
                is_source=True,
                is_core=True,
                purpose="Core entrypoint",
                llm_summary="Main file summary",
                analysis_status=AnalysisStatus.COMPLETED.value,
            )
            session.add(file_rec)
            await session.flush()
            await session.commit()

        project_root_str = str(Path(__file__).resolve().parent.parent)
        workflow = GenerateManualWorkflow(project_root_str)
        result = await workflow.execute()
        self.assertTrue(result["generated"])
        manual_path = Path(result["manual_path"])
        self.assertTrue(manual_path.exists())
        # Clean up manual file
        if manual_path.exists():
            manual_path.unlink()

    async def test_background_analysis_loop_and_progress_tracking(self):
        """Test that the background analyzer loop can process tasks and report progress correctly."""
        # 1. Populate the DB with pending tasks
        async with get_session() as session:
            file_rec = File(
                path="src/dummy_math.py",
                filename="dummy_math.py",
                extension=".py",
                language="python",
                file_type="source",
                size_bytes=150,
                hash="dummy_hash_math",
                last_modified=datetime.utcnow(),
                is_source=True,
                analysis_status=AnalysisStatus.PENDING.value,
            )
            session.add(file_rec)
            await session.flush()

            sym_rec = Symbol(
                file_id=file_rec.id,
                name="compute_loss",
                qualified_name="dummy_math.compute_loss",
                symbol_type="function",
                start_line=10,
                end_line=20,
            )
            session.add(sym_rec)
            await session.flush()

            eq_rec = Equation(
                file_id=file_rec.id,
                name="loss_formula",
                expression="L = sum(y - y_hat) ** 2",
                start_line=15,
                end_line=15,
            )
            session.add(eq_rec)
            await session.flush()

            # Add tasks
            session.add(
                LLMAnalysisRecord(
                    target_type="file",
                    target_id=file_rec.id,
                    prompt_name="analyze_file",
                    prompt_version="1.0",
                    model_name="patcher-main",
                    input_context_hash="h1",
                    output_json="{}",
                    status=AnalysisStatus.PENDING.value,
                )
            )
            session.add(
                LLMAnalysisRecord(
                    target_type="symbol",
                    target_id=sym_rec.id,
                    prompt_name="analyze_symbol",
                    prompt_version="1.0",
                    model_name="patcher-main",
                    input_context_hash="h2",
                    output_json="{}",
                    status=AnalysisStatus.PENDING.value,
                )
            )
            session.add(
                LLMAnalysisRecord(
                    target_type="equation",
                    target_id=eq_rec.id,
                    prompt_name="analyze_equation",
                    prompt_version="1.0",
                    model_name="patcher-main",
                    input_context_hash="h3",
                    output_json="{}",
                    status=AnalysisStatus.PENDING.value,
                )
            )
            await session.commit()

        # Create dummy source code file to satisfy AST parser during context building
        dummy_math_file = Path(__file__).resolve().parent.parent / "src/dummy_math.py"
        dummy_math_file.parent.mkdir(parents=True, exist_ok=True)
        dummy_math_file.write_text(
            "def compute_loss(y, y_hat):\n"
            "    # L = sum(y - y_hat) ** 2\n"
            "    return (y - y_hat) ** 2\n",
            encoding="utf-8"
        )

        try:
            # 2. Mock the analyzer client
            analyzer = get_analyzer(mode="server_driven")
            analyzer.settings.llm_mode = "server_driven"
            mock_client = MagicMock()
            mock_create = AsyncMock()

            async def mock_completion_create(*args, **kwargs):
                schema_class = kwargs.get("response_model")
                if schema_class == FileAnalysisResult:
                    return FileAnalysisResult(
                        summary="Computes loss calculations.",
                        is_core=True,
                        key_concepts=["loss"],
                        risk_notes=[],
                        confidence=0.9,
                    )
                elif schema_class == SymbolAnalysisResult:
                    return SymbolAnalysisResult(
                        responsibility="Responsibility description.",
                        side_effects=[],
                        confidence=0.8,
                    )
                elif schema_class == EquationAnalysisResult:
                    return EquationAnalysisResult(
                        name="loss_formula_named",
                        mathematical_meaning="Squared error loss",
                        algorithmic_role="optimization objective",
                        confidence=0.9,
                        evidence="L = sum(y - y_hat) ** 2",
                    )
                return None

            mock_create.side_effect = mock_completion_create
            mock_client.chat.completions.create = mock_create
            analyzer._client = mock_client

            # 3. Start background runner
            project_root_str = str(Path(__file__).resolve().parent.parent)
            runner.start(project_root_str)

            # Wait for completion
            for _ in range(50):
                if not runner.is_running:
                    break
                await asyncio.sleep(0.1)

            self.assertFalse(runner.is_running)
            self.assertIsNone(runner.last_error)

            # 4. Verify DB commits
            async with get_session() as session:
                f_db = (await session.execute(select(File).where(File.path == "src/dummy_math.py"))).scalar_one()
                self.assertEqual(f_db.llm_summary, "Computes loss calculations.")
                self.assertTrue(f_db.is_core)

                s_db = (await session.execute(select(Symbol).where(Symbol.name == "compute_loss"))).scalar_one()
                self.assertEqual(s_db.responsibility, "Responsibility description.")

                e_db = (await session.execute(select(Equation).where(Equation.name == "loss_formula_named"))).scalar_one()
                self.assertEqual(e_db.mathematical_meaning, "Squared error loss")

        finally:
            if dummy_math_file.exists():
                dummy_math_file.unlink()


if __name__ == "__main__":
    unittest.main()
