import asyncio
import sys
import traceback
import os

os.environ.setdefault("PYTHONUNBUFFERED", "1")

from project_memory_mcp.db.connection import init_db, get_session
from project_memory_mcp.db.models import LLMAnalysisRecord, File, AnalysisStatus
from project_memory_mcp.llm_analysis.analyzer import get_analyzer
from project_memory_mcp.static_analysis.static_locator import StaticLocator
from sqlalchemy import select
from pathlib import Path

PROJECT_ROOT = Path(".").resolve()
_locator = None


def _get_locator():
    global _locator
    if _locator is None:
        _locator = StaticLocator()
    return _locator


def _read_source(rel_path):
    try:
        return (PROJECT_ROOT / rel_path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _file_context(file_record):
    language = file_record.language or "unknown"
    rel_path = file_record.path
    imports = symbols = ""
    if language != "unknown":
        try:
            a = _get_locator().analyze_file(str(PROJECT_ROOT / rel_path))
            imports = ", ".join(sorted({i.name for i in (a.imports or [])}))
            symbols = ", ".join(
                sorted({f.name for f in (a.functions or [])} | {c.name for c in (a.classes or [])})
            )
        except Exception:
            pass
    return {
        "task_id": f"file_{file_record.id}",
        "task_type": "file",
        "target_path": rel_path,
        "target_name": None,
        "file_id": file_record.id,
        "file_path": rel_path,
        "language": language,
        "source_code": _read_source(rel_path),
        "imports": imports,
        "symbols": symbols,
    }


async def main():
    await init_db()
    az = get_analyzer(mode="server_driven")
    print("client:", az._client)
    print("provider:", az.settings.llm_provider, "model:", az.settings.llm_model, "base:", az.settings.llm_api_base)

    async with get_session() as session:
        rec = (await session.execute(
            select(LLMAnalysisRecord).where(
                (LLMAnalysisRecord.target_type == "file")
                & (LLMAnalysisRecord.status == AnalysisStatus.PENDING.value)
            ).order_by(LLMAnalysisRecord.id).limit(1)
        )).scalar_one_or_none()
        target = (await session.execute(select(File).where(File.id == rec.target_id))).scalar_one()
        ctx = _file_context(target)
        print("ctx keys:", list(ctx.keys()))
        print("target:", target.path, "lang:", target.language, "src_len:", len(ctx["source_code"]))

    print("--- calling LLM ---", flush=True)
    try:
        result = await az.analyze("analyze_file", ctx)
        print("status:", result.status)
        print("conf:", result.confidence)
        print("result:", result.result)
    except Exception as e:
        print("EXC:", repr(e))
        traceback.print_exc()


asyncio.run(main())

