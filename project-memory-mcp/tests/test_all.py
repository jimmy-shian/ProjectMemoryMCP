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
    Variable,
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
        self.assertEqual(settings.llm_mode, "server_driven")
        self.assertEqual(settings.llm_api_base, "http://localhost:4000/v1")

    def test_nested_config_loading(self):
        """Test documented nested configuration is flattened for runtime settings."""
        config = load_config(Path(__file__).resolve().parent.parent / "config.yaml")
        self.assertEqual(config["llm_mode"], "server_driven")
        self.assertEqual(config["llm_provider"], "myself")
        self.assertEqual(config["llm_api_base"], "http://localhost:4000/v1")
        self.assertEqual(config["db_path"], ".project-memory/project_knowledge.db")

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

    async def test_background_loop_handles_duplicate_analysis_records(self):
        """Regression: LLMAnalysisRecord has no unique (target_type,target_id) constraint.

        Duplicate PENDING rows for the same target must not crash the loop with
        'Multiple rows were found' from a non-unique scalar_one_or_none() lookup.
        """
        async with get_session() as session:
            file_rec = File(
                path="src/dummy_math2.py",
                filename="dummy_math2.py",
                extension=".py",
                language="python",
                file_type="source",
                size_bytes=120,
                hash="dummy_hash_math2",
                last_modified=datetime.utcnow(),
                is_source=True,
                analysis_status=AnalysisStatus.PENDING.value,
            )
            session.add(file_rec)
            await session.flush()

            # Insert TWO duplicate PENDING records for the SAME file target.
            for ctx_hash in ("dup1", "dup2"):
                session.add(
                    LLMAnalysisRecord(
                        target_type="file",
                        target_id=file_rec.id,
                        prompt_name="analyze_file",
                        prompt_version="1.0",
                        model_name="patcher-main",
                        input_context_hash=ctx_hash,
                        output_json="{}",
                        status=AnalysisStatus.PENDING.value,
                    )
                )
            await session.commit()

        dummy_math_file = Path(__file__).resolve().parent.parent / "src/dummy_math2.py"
        dummy_math_file.parent.mkdir(parents=True, exist_ok=True)
        dummy_math_file.write_text(
            "def compute_loss2(y, y_hat):\n"
            "    return (y - y_hat) ** 2\n",
            encoding="utf-8",
        )

        try:
            analyzer = get_analyzer(mode="server_driven")
            analyzer.settings.llm_mode = "server_driven"
            mock_client = MagicMock()
            async def mock_completion_create(*args, **kwargs):
                return FileAnalysisResult(
                    summary="Computes loss 2.",
                    is_core=False,
                    key_concepts=["loss2"],
                    risk_notes=[],
                    confidence=0.7,
                )
            mock_client.chat.completions.create = AsyncMock(side_effect=mock_completion_create)
            analyzer._client = mock_client

            project_root_str = str(Path(__file__).resolve().parent.parent)
            runner.start(project_root_str)

            for _ in range(50):
                if not runner.is_running:
                    break
                await asyncio.sleep(0.1)

            self.assertFalse(runner.is_running, "loop should finish")
            # The original bug aborted the entire loop on the duplicate lookup,
            # surfacing 'Multiple rows were found' in last_error.
            self.assertIsNone(
                runner.last_error,
                f"loop failed (was Multiple rows were found?): {runner.last_error}",
            )

            async with get_session() as session:
                f_db = (
                    await session.execute(select(File).where(File.path == "src/dummy_math2.py"))
                ).scalar_one()
                self.assertEqual(f_db.llm_summary, "Computes loss 2.")

                pending = (
                    await session.execute(
                        select(LLMAnalysisRecord).where(
                            (LLMAnalysisRecord.target_type == "file")
                            & (LLMAnalysisRecord.target_id == f_db.id)
                            & (LLMAnalysisRecord.status == AnalysisStatus.PENDING.value)
                        )
                    )
                ).scalars().all()
                self.assertEqual(
                    len(pending),
                    0,
                    "both duplicate records should have been processed (no PENDING left)",
                )
        finally:
            if dummy_math_file.exists():
                dummy_math_file.unlink()

    async def test_llm_derived_edge_creation(self):
        """Test creation of USES_EQUATION edges from Symbol LLM analysis."""
        from project_memory_mcp.workflows.rescan_changed_files import add_llm_derived_edges

        async with get_session() as session:
            file_rec = File(
                path="src/test_edges.py",
                filename="test_edges.py",
                extension=".py",
                language="python",
                file_type="source",
                size_bytes=100,
                hash="hash_edges",
                last_modified=datetime.utcnow(),
                is_source=True,
            )
            session.add(file_rec)
            await session.flush()

            symbol = Symbol(
                file_id=file_rec.id,
                name="run_model",
                qualified_name="test_edges.run_model",
                symbol_type="function",
                start_line=1,
                end_line=10,
            )
            session.add(symbol)

            eq = Equation(
                file_id=file_rec.id,
                name="forward_pass",
                expression="y = w * x + b",
                start_line=5,
                end_line=5,
            )
            session.add(eq)
            await session.flush()

            # Create completed symbol LLM record
            llm_rec = LLMAnalysisRecord(
                target_type="symbol",
                target_id=symbol.id,
                prompt_name="analyze_symbol",
                prompt_version="1.0",
                model_name="test-model",
                input_context_hash="hash_ctx",
                output_json='{"responsibility": "Run model", "related_equations": ["forward_pass"], "confidence": 0.9}',
                status="completed",
                confidence=0.9,
            )
            session.add(llm_rec)
            await session.commit()

        # Run LLM edge extraction
        async with get_session() as session:
            await add_llm_derived_edges(session)
            await session.commit()

        # Verify edge created
        async with get_session() as session:
            stmt = select(GraphEdge).where(
                (GraphEdge.source_type == "symbol") &
                (GraphEdge.source_id == symbol.id) &
                (GraphEdge.target_type == "equation") &
                (GraphEdge.target_id == eq.id) &
                (GraphEdge.edge_type == "USES_EQUATION")
            )
            edge = (await session.execute(stmt)).scalar_one_or_none()
            self.assertIsNotNone(edge)
            self.assertEqual(edge.confidence, 0.9)

            # Re-run to verify idempotency (no duplicates)
            await add_llm_derived_edges(session)
            await session.commit()

            stmt_all = select(GraphEdge).where(
                (GraphEdge.source_type == "symbol") &
                (GraphEdge.source_id == symbol.id) &
                (GraphEdge.target_type == "equation") &
                (GraphEdge.target_id == eq.id) &
                (GraphEdge.edge_type == "USES_EQUATION")
            )
            edges = (await session.execute(stmt_all)).scalars().all()
            self.assertEqual(len(edges), 1)

    async def test_equation_variable_extraction(self):
        """Test Variable record upsert and Equation -> Variable edge creation from Equation LLM analysis."""
        from project_memory_mcp.workflows.rescan_changed_files import add_llm_derived_edges

        async with get_session() as session:
            file_rec = File(
                path="src/test_vars.py",
                filename="test_vars.py",
                extension=".py",
                language="python",
                file_type="source",
                size_bytes=100,
                hash="hash_vars",
                last_modified=datetime.utcnow(),
                is_source=True,
            )
            session.add(file_rec)
            await session.flush()

            eq = Equation(
                file_id=file_rec.id,
                symbol_id=42,
                name="loss_eq",
                expression="L = (y - y_hat) ** 2",
                start_line=1,
                end_line=2,
            )
            session.add(eq)
            await session.flush()

            llm_rec = LLMAnalysisRecord(
                target_type="equation",
                target_id=eq.id,
                prompt_name="analyze_equation",
                prompt_version="1.0",
                model_name="test-model",
                input_context_hash="hash_ctx",
                output_json='{"equation_type": "loss", "name": "loss_eq", "mathematical_meaning": "mean squared error", "algorithmic_role": "loss function", "inputs": ["y", "y_hat"], "outputs": ["L"], "intermediate_variables": ["diff"], "constants": ["coeff"], "confidence": 0.95, "evidence": "L = (y - y_hat) ** 2"}',
                status="completed",
                confidence=0.95,
            )
            session.add(llm_rec)
            await session.commit()

        # Run LLM edge extraction
        async with get_session() as session:
            await add_llm_derived_edges(session)
            await session.commit()

        # Verify variables and edges created
        async with get_session() as session:
            # Inputs
            var_stmt = select(Variable).where(
                (Variable.file_id == file_rec.id) &
                (Variable.symbol_id == 42) &
                (Variable.name == "y") &
                (Variable.role == "input")
            )
            var_y = (await session.execute(var_stmt)).scalar_one_or_none()
            self.assertIsNotNone(var_y)

            edge_stmt = select(GraphEdge).where(
                (GraphEdge.source_type == "equation") &
                (GraphEdge.source_id == eq.id) &
                (GraphEdge.target_type == "variable") &
                (GraphEdge.target_id == var_y.id) &
                (GraphEdge.edge_type == "EQUATION_INPUT")
            )
            edge_input = (await session.execute(edge_stmt)).scalar_one_or_none()
            self.assertIsNotNone(edge_input)

            # Outputs
            var_stmt = select(Variable).where(
                (Variable.file_id == file_rec.id) &
                (Variable.symbol_id == 42) &
                (Variable.name == "L") &
                (Variable.role == "output")
            )
            var_l = (await session.execute(var_stmt)).scalar_one_or_none()
            self.assertIsNotNone(var_l)

            edge_stmt = select(GraphEdge).where(
                (GraphEdge.source_type == "equation") &
                (GraphEdge.source_id == eq.id) &
                (GraphEdge.target_type == "variable") &
                (GraphEdge.target_id == var_l.id) &
                (GraphEdge.edge_type == "EQUATION_OUTPUT")
            )
            edge_output = (await session.execute(edge_stmt)).scalar_one_or_none()
            self.assertIsNotNone(edge_output)

            # Check idempotency
            await add_llm_derived_edges(session)
            await session.commit()
            
            stmt_all = select(GraphEdge).where(
                (GraphEdge.source_type == "equation") &
                (GraphEdge.source_id == eq.id) &
                (GraphEdge.target_type == "variable") &
                (GraphEdge.target_id == var_y.id)
            )
            edges = (await session.execute(stmt_all)).scalars().all()
            self.assertEqual(len(edges), 1)

    async def test_stale_llm_record_ignored(self):
        """Test that stale LLMAnalysisRecord entries are ignored."""
        from project_memory_mcp.workflows.rescan_changed_files import add_llm_derived_edges

        async with get_session() as session:
            file_rec = File(
                path="src/test_stale.py",
                filename="test_stale.py",
                extension=".py",
                language="python",
                file_type="source",
                size_bytes=100,
                hash="hash_stale",
                last_modified=datetime.utcnow(),
                is_source=True,
            )
            session.add(file_rec)
            await session.flush()

            symbol = Symbol(
                file_id=file_rec.id,
                name="run_model",
                qualified_name="test_stale.run_model",
                symbol_type="function",
                start_line=1,
                end_line=10,
            )
            session.add(symbol)

            eq = Equation(
                file_id=file_rec.id,
                name="forward_pass",
                expression="y = w * x + b",
                start_line=5,
                end_line=5,
            )
            session.add(eq)
            await session.flush()

            # Create stale symbol LLM record
            llm_rec = LLMAnalysisRecord(
                target_type="symbol",
                target_id=symbol.id,
                prompt_name="analyze_symbol",
                prompt_version="1.0",
                model_name="test-model",
                input_context_hash="hash_ctx",
                output_json='{"responsibility": "Run model", "related_equations": ["forward_pass"], "confidence": 0.9}',
                status="stale",
            )
            session.add(llm_rec)
            await session.commit()

        # Run LLM edge extraction
        async with get_session() as session:
            await add_llm_derived_edges(session)
            await session.commit()

        # Verify USES_EQUATION edge is NOT created
        async with get_session() as session:
            stmt = select(GraphEdge).where(
                (GraphEdge.source_type == "symbol") &
                (GraphEdge.source_id == symbol.id) &
                (GraphEdge.target_type == "equation") &
                (GraphEdge.target_id == eq.id) &
                (GraphEdge.edge_type == "USES_EQUATION")
            )
            edge = (await session.execute(stmt)).scalar_one_or_none()
            self.assertIsNone(edge)

    async def test_duplicate_variable_resolution_distinct_equations(self):
        """Test that distinct variables with same name under different symbols/equations do not collide."""
        from project_memory_mcp.workflows.rescan_changed_files import add_llm_derived_edges

        async with get_session() as session:
            file_rec = File(
                path="src/test_collide.py",
                filename="test_collide.py",
                extension=".py",
                language="python",
                file_type="source",
                size_bytes=100,
                hash="hash_collide",
                last_modified=datetime.utcnow(),
                is_source=True,
            )
            session.add(file_rec)
            await session.flush()

            eq_a = Equation(
                file_id=file_rec.id,
                symbol_id=101,
                name="eq_a",
                expression="y = x + 1",
                start_line=1,
                end_line=2,
            )
            eq_b = Equation(
                file_id=file_rec.id,
                symbol_id=102,
                name="eq_b",
                expression="x = t",
                start_line=10,
                end_line=11,
            )
            session.add(eq_a)
            session.add(eq_b)
            await session.flush()

            # completed records for both using 'x'
            session.add(LLMAnalysisRecord(
                target_type="equation",
                target_id=eq_a.id,
                prompt_name="analyze_equation",
                prompt_version="1.0",
                model_name="test",
                input_context_hash="h1",
                output_json='{"inputs": ["x"], "outputs": ["y"], "confidence": 0.9, "evidence": ""}',
                status="completed",
            ))
            session.add(LLMAnalysisRecord(
                target_type="equation",
                target_id=eq_b.id,
                prompt_name="analyze_equation",
                prompt_version="1.0",
                model_name="test",
                input_context_hash="h2",
                output_json='{"inputs": ["t"], "outputs": ["x"], "confidence": 0.9, "evidence": ""}',
                status="completed",
            ))
            await session.commit()

        # Run extraction
        async with get_session() as session:
            await add_llm_derived_edges(session)
            await session.commit()

        # Verify two distinct variables were created
        async with get_session() as session:
            stmt = select(Variable).where(
                (Variable.file_id == file_rec.id) & (Variable.name == "x")
            )
            vars_found = (await session.execute(stmt)).scalars().all()
            self.assertEqual(len(vars_found), 2)
            
            roles = {v.role for v in vars_found}
            symbol_ids = {v.symbol_id for v in vars_found}
            self.assertIn("input", roles)
            self.assertIn("output", roles)
            self.assertIn(101, symbol_ids)
            self.assertIn(102, symbol_ids)

    async def test_incremental_rescan_and_cleanup(self):
        """Test that RescanChangedFilesWorkflow deletes stale symbols, equations, variables, and edges."""
        from project_memory_mcp.workflows.rescan_changed_files import RescanChangedFilesWorkflow

        # Create dummy file with some calculations
        dummy_file = Path(__file__).resolve().parent.parent / "src/dummy_rescan.py"
        dummy_file.parent.mkdir(parents=True, exist_ok=True)
        dummy_file.write_text(
            "def compute_loss(y, y_hat):\n"
            "    # L = (y - y_hat) ** 2\n"
            "    return (y - y_hat) ** 2\n",
            encoding="utf-8"
        )

        try:
            # 1. Run rescan workflow to index it
            project_root_str = str(Path(__file__).resolve().parent.parent)
            workflow = RescanChangedFilesWorkflow(project_root_str)
            res = await workflow.execute()
            self.assertGreaterEqual(res["files_added"], 1)

            # Verify symbol and equation exist
            async with get_session() as session:
                stmt_sym = select(Symbol).where(Symbol.name == "compute_loss")
                sym_old = (await session.execute(stmt_sym)).scalar_one_or_none()
                self.assertIsNotNone(sym_old)

                stmt_eq = select(Equation).where(Equation.name == "compute_loss")
                eq_old = (await session.execute(stmt_eq)).scalar_one_or_none()
                self.assertIsNotNone(eq_old)

                # Assert DEFINES edge exists
                stmt_edge = select(GraphEdge).where(
                    (GraphEdge.source_type == "file") &
                    (GraphEdge.target_type == "symbol") &
                    (GraphEdge.target_id == sym_old.id)
                )
                defines_edge = (await session.execute(stmt_edge)).scalar_one_or_none()
                self.assertIsNotNone(defines_edge)

            # 2. Modify dummy file: replace compute_loss with calculate_gradient
            dummy_file.write_text(
                "def calculate_gradient(a, b):\n"
                "    # sum_val = a + b\n"
                "    return a + b\n",
                encoding="utf-8"
            )

            # Run rescan again
            workflow = RescanChangedFilesWorkflow(project_root_str)
            res2 = await workflow.execute()
            self.assertEqual(res2["files_changed"], 1)

            # Verify compute_loss is deleted and calculate_gradient is added
            async with get_session() as session:
                # Check compute_loss deleted
                stmt_sym = select(Symbol).where(Symbol.name == "compute_loss")
                self.assertIsNone((await session.execute(stmt_sym)).scalar_one_or_none())

                stmt_eq = select(Equation).where(Equation.name == "compute_loss")
                self.assertIsNone((await session.execute(stmt_eq)).scalar_one_or_none())

                # Check calculate_gradient created
                stmt_sym = select(Symbol).where(Symbol.name == "calculate_gradient")
                sym_new = (await session.execute(stmt_sym)).scalar_one_or_none()
                self.assertIsNotNone(sym_new)

                stmt_eq = select(Equation).where(Equation.name == "calculate_gradient")
                self.assertIsNotNone((await session.execute(stmt_eq)).scalar_one_or_none())

                # Verify defines edge pointing to old symbol was cleaned up
                stmt_edge_old = select(GraphEdge).where(
                    (GraphEdge.source_type == "file") &
                    (GraphEdge.target_type == "symbol") &
                    (GraphEdge.target_id == sym_old.id)
                )
                self.assertIsNone((await session.execute(stmt_edge_old)).scalar_one_or_none())

                # Verify defines edge pointing to new symbol was created
                stmt_edge_new = select(GraphEdge).where(
                    (GraphEdge.source_type == "file") &
                    (GraphEdge.target_type == "symbol") &
                    (GraphEdge.target_id == sym_new.id)
                )
                self.assertIsNotNone((await session.execute(stmt_edge_new)).scalar_one_or_none())

        finally:
            if dummy_file.exists():
                dummy_file.unlink()

    async def test_update_graph_edges_no_unique_collision(self):
        """Regression: _update_graph_edges must not collapse same-source edges.

        Previously it issued ``UPDATE graph_edges SET target_id=0`` for all
        IMPORTS/CALLS edges. When a file imported two distinct modules, both
        edges shared source ``(file, file_id)`` and got the same
        ``target_id=0``, colliding on the ``uq_edge_unique`` constraint and
        raising sqlite3.IntegrityError. We now re-resolve in place per edge
        and delete unresolved/duplicate edges instead.
        """
        from project_memory_mcp.workflows.rescan_changed_files import (
            RescanChangedFilesWorkflow,
        )

        async with get_session() as session:
            # Two target modules the importer will resolve to.
            mod_a = File(
                path="src/mod_a.py", filename="mod_a.py", extension=".py",
                language="python", file_type="source", size_bytes=10,
                hash="ha", last_modified=datetime.utcnow(), is_source=True,
            )
            mod_b = File(
                path="src/mod_b.py", filename="mod_b.py", extension=".py",
                language="python", file_type="source", size_bytes=10,
                hash="hb", last_modified=datetime.utcnow(), is_source=True,
            )
            session.add_all([mod_a, mod_b])
            await session.flush()
            mod_a_id, mod_b_id = mod_a.id, mod_b.id

            importer = File(
                path="src/importer.py", filename="importer.py", extension=".py",
                language="python", file_type="source", size_bytes=10,
                hash="hi", last_modified=datetime.utcnow(), is_source=True,
            )
            session.add(importer)
            await session.flush()
            importer_id = importer.id

            # Two IMPORTS edges from the SAME file, each already resolved to a
            # DIFFERENT target file. The old blanket ``UPDATE ... SET
            # target_id=0`` would collapse them onto the shared key
            # (file, file_id, file, 0, IMPORTS) and trip uq_edge_unique.
            session.add(GraphEdge(
                source_type="file", source_id=importer_id,
                target_type="file", target_id=mod_a_id,
                edge_type="IMPORTS", evidence="Import: src.mod_a",
                confidence=0.9, created_by="static_locator",
            ))
            session.add(GraphEdge(
                source_type="file", source_id=importer_id,
                target_type="file", target_id=mod_b_id,
                edge_type="IMPORTS", evidence="Import: src.mod_b",
                confidence=0.9, created_by="static_locator",
            ))

            # A CALLS edge (already resolved) so the call-resolution branch is
            # exercised too.
            sym = Symbol(
                file_id=importer_id, name="helper",
                qualified_name="importer.helper", symbol_type="function",
                start_line=1, end_line=2,
            )
            session.add(sym)
            await session.flush()
            sym_id = sym.id
            session.add(GraphEdge(
                source_type="symbol", source_id=sym_id,
                target_type="symbol", target_id=sym_id,
                edge_type="CALLS", evidence="Call to importer.helper",
                confidence=0.8, created_by="static_locator",
            ))

        # Must not raise sqlite3.IntegrityError (UNIQUE constraint failed).
        workflow = RescanChangedFilesWorkflow(str(Path(__file__).resolve().parent.parent))
        await workflow._update_graph_edges()

        # Verify IMPORTS edges resolved to distinct file targets (no collapse).
        async with get_session() as session:
            stmt = select(GraphEdge).where(
                (GraphEdge.source_type == "file") &
                (GraphEdge.source_id == importer_id) &
                (GraphEdge.edge_type == "IMPORTS")
            )
            edges = (await session.execute(stmt)).scalars().all()
            target_ids = {e.target_id for e in edges}
            self.assertEqual(len(edges), 2, "both IMPORTS edges should survive")
            self.assertEqual(target_ids, {mod_a_id, mod_b_id},
                            "edges resolved to distinct module file ids")

            # CALLS edge resolved to the symbol id.
            call_edges = (
                await session.execute(
                    select(GraphEdge).where(
                        (GraphEdge.source_type == "symbol") &
                        (GraphEdge.source_id == sym_id) &
                        (GraphEdge.edge_type == "CALLS")
                    )
                )
            ).scalars().all()
            self.assertTrue(call_edges, "CALLS edge should survive")
            self.assertEqual(call_edges[0].target_id, sym_id)


        """Test that ApplyEditWorkflow triggers RescanChangedFilesWorkflow to keep DB synced."""
        from project_memory_mcp.workflows.apply_edit import ApplyEditWorkflow

        # Create dummy file with some calculations
        dummy_file = Path(__file__).resolve().parent.parent / "src/dummy_edit.py"
        dummy_file.parent.mkdir(parents=True, exist_ok=True)
        dummy_file.write_text(
            "def original_func():\n"
            "    # result = 1\n"
            "    return 1\n",
            encoding="utf-8"
        )

        try:
            # Rescan initially to register file
            project_root_str = str(Path(__file__).resolve().parent.parent)
            from project_memory_mcp.workflows.rescan_changed_files import RescanChangedFilesWorkflow
            await RescanChangedFilesWorkflow(project_root_str).execute()

            # Verify original_func in DB
            async with get_session() as session:
                stmt = select(Symbol).where(Symbol.name == "original_func")
                self.assertIsNotNone((await session.execute(stmt)).scalar_one_or_none())

            # Apply edit to rename original_func to edited_func
            editor = ApplyEditWorkflow(project_root_str)
            changes = [
                {
                    "type": "replace",
                    "start_line": 1,
                    "end_line": 3,
                    "new_content": "def edited_func():\n    # result = 2\n    return 2"
                }
            ]
            res = await editor.apply_edit("src/dummy_edit.py", changes)
            self.assertTrue(res["success"])

            # Verify database was automatically synced
            async with get_session() as session:
                stmt_orig = select(Symbol).where(Symbol.name == "original_func")
                self.assertIsNone((await session.execute(stmt_orig)).scalar_one_or_none())

                stmt_edit = select(Symbol).where(Symbol.name == "edited_func")
                self.assertIsNotNone((await session.execute(stmt_edit)).scalar_one_or_none())

        finally:
            if dummy_file.exists():
                dummy_file.unlink()


if __name__ == "__main__":
    unittest.main()
