"""Drive the agent-driven analysis loop to completion by calling the LLM.

This script materializes the README "agent-driven" loop (get_next_analysis_task
-> analyze -> submit_*_analysis) for ALL pending tasks in the local
project_knowledge.db, using the configured OpenAI-compatible LLM endpoint.

It must be run with cwd = the target project root so that
``.project-memory/project_knowledge.db`` resolves to that project's database:

    uv run --project <PMCPS repo> --directory <target project> \\
        python scripts/run_analysis_loop.py

The LLM endpoint/model come from Settings (llm_provider="myself",
llm_api_base, llm_model) which already match kilo.jsonc.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

# Force unbuffered line-buffered stdout so background logs stream live.
try:
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(line_buffering=True, encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

# Aliased print() that always flushes, so progress is visible when run in background.
_orig_print = print


def print(*args, **kwargs):  # type: ignore[no-redef]
    kwargs.setdefault("flush", True)
    _orig_print(*args, **kwargs)

from sqlalchemy import select

from project_memory_mcp.db.connection import get_session, init_db
from project_memory_mcp.db.models import (
    AnalysisStatus,
    Equation,
    File,
    LLMAnalysisRecord,
    Symbol,
)
from project_memory_mcp.llm_analysis.analyzer import get_analyzer


# ---------------------------------------------------------------------------
# Context builders (mirror mcp_tools.memory._build_analysis_task_output)
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(".").resolve()
locator = None  # lazily created


def _get_locator():
    global locator
    if locator is None:
        from project_memory_mcp.static_analysis.static_locator import StaticLocator

        locator = StaticLocator()
    return locator


def _read_source(rel_path: str) -> str:
    full = PROJECT_ROOT / rel_path
    try:
        return full.read_text(encoding="utf-8", errors="replace")
    except Exception:
        try:
            return Path(rel_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""


def _file_context(file_record: File) -> dict[str, Any]:
    language = file_record.language or "unknown"
    rel_path = file_record.path
    imports = ""
    symbols = ""
    if language != "unknown":
        try:
            analysis = _get_locator().analyze_file(str(PROJECT_ROOT / rel_path))
            imports = ", ".join(
                sorted({i.name for i in (analysis.imports or [])})
            )
            symbols = ", ".join(
                sorted(
                    {f.name for f in (analysis.functions or [])}
                    | {c.name for c in (analysis.classes or [])}
                )
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


def _symbol_context(symbol: Symbol, file_record: File | None) -> dict[str, Any]:
    rel_path = file_record.path if file_record else ""
    language = (file_record.language if file_record else None) or "unknown"
    sym_source = ""
    if rel_path:
        sym_source = _read_source(rel_path)
    return {
        "task_id": f"symbol_{symbol.id}",
        "task_type": "symbol",
        "target_path": symbol.qualified_name or symbol.name,
        "target_name": symbol.name,
        "symbol_id": symbol.id,
        "file_id": symbol.file_id,
        "file_path": rel_path,
        "language": language,
        "symbol_name": symbol.name,
        "symbol_type": symbol.symbol_type,
        "signature": symbol.signature or "",
        "docstring": symbol.docstring or "",
        "parent_class": "",
        "source_code": sym_source,
        "called_functions": "",
        "calling_functions": "",
    }


def _equation_context(
    equation: Equation, file_record: File | None
) -> dict[str, Any]:
    rel_path = file_record.path if file_record else ""
    language = (file_record.language if file_record else None) or "unknown"
    return {
        "task_id": f"equation_{equation.id}",
        "task_type": "equation",
        "target_path": equation.name or "",
        "target_name": equation.name,
        "equation_id": equation.id,
        "file_id": equation.file_id,
        "file_path": rel_path,
        "language": language,
        "equation_name": equation.name or "",
        "containing_function": "",
        "containing_class": "",
        "expression": equation.expression or "",
        "surrounding_code": _read_source(rel_path) if rel_path else "",
        "variables_in_scope": "",
    }


PROMPT_BY_TYPE = {"file": "analyze_file", "symbol": "analyze_symbol", "equation": "analyze_equation"}


# ---------------------------------------------------------------------------
# Persistence (mirror mcp_tools.memory submit_*_analysis)
# ---------------------------------------------------------------------------


async def _apply_file_result(file_record: File, result: AnalysisResult) -> None:
    data = result.result or {}
    file_record.purpose = data.get("purpose", "")
    file_record.llm_summary = data.get("summary", "")
    file_record.llm_confidence = data.get("confidence", 0.0)
    file_record.is_core = data.get("is_core", False)
    file_record.key_concepts = json.dumps(data.get("key_concepts", []), ensure_ascii=False)
    file_record.risk_notes = json.dumps(data.get("risk_notes", []), ensure_ascii=False)
    file_record.analysis_status = AnalysisStatus.COMPLETED.value


async def _apply_symbol_result(symbol: Symbol, result: AnalysisResult) -> None:
    data = result.result or {}
    resp = data.get("responsibility", "")
    symbol.llm_summary = resp
    symbol.responsibility = resp
    symbol.side_effects = str(data.get("side_effects", []))
    symbol.confidence = data.get("confidence", 0.0)


async def _apply_equation_result(equation: Equation, result: AnalysisResult) -> None:
    data = result.result or {}
    equation.name = data.get("name", equation.name)
    equation.equation_type = data.get("equation_type", "unknown")
    equation.mathematical_meaning = data.get("mathematical_meaning", "")
    equation.physical_meaning = data.get("physical_meaning")
    equation.algorithmic_role = data.get("algorithmic_role", "")
    equation.inputs_json = json.dumps(data.get("inputs", []))
    equation.outputs_json = json.dumps(data.get("outputs", []))
    equation.intermediate_variables_json = json.dumps(
        data.get("intermediate_variables", [])
    )
    equation.constants_json = json.dumps(data.get("constants", []))
    equation.units_json = json.dumps(data.get("units", {}))
    equation.assumptions = str(data.get("assumptions", []))
    equation.confidence = data.get("confidence", 0.0)


async def _mark_record_completed(record: LLMAnalysisRecord, result: AnalysisResult) -> None:
    record.output_json = str(result.result)
    record.confidence = result.confidence
    record.status = AnalysisStatus.COMPLETED.value


async def _mark_record_failed(record: LLMAnalysisRecord, err: str) -> None:
    record.status = AnalysisStatus.FAILED.value
    record.output_json = json.dumps({"error": err[:500]})


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


async def analyze_one(
    analyzer,
    prompt_name: str,
    context: dict[str, Any],
) -> AnalysisResult:
    """Call the LLM via the analyzer; on failure return a FAILED AnalysisResult."""
    try:
        result = await analyzer.analyze(prompt_name, context)
        ok = bool(result and result.result)
        if not ok:
            print(
                f"      analyze returned empty result: status={result.status} "
                f"error={getattr(result, 'error', None)} has_result={bool(result.result if result else False)}",
                flush=True,
            )
        return result
    except Exception as exc:  # noqa: BLE001
        tb = traceback.format_exc(limit=6)
        print(f"      analyze raised: {exc}\n{tb}", flush=True)
        return AnalysisResult(
            task_id=context.get("task_id", "?"),
            task_type=context.get("task_type", ""),
            target_path=context.get("target_path", ""),
            target_name=context.get("target_name"),
            result={},
            status=AnalysisStatus.FAILED,
            confidence=0.0,
            error=str(exc),
        )


async def run_layer(task_type: str, analyzer) -> tuple[int, int, int]:
    """Process all pending tasks of one layer. Returns (done, failed, skipped)."""
    prompt_name = PROMPT_BY_TYPE[task_type]
    done = failed = skipped = 0
    total = 0

    # Count pending for progress
    async with get_session() as session:
        cnt = (
            await session.execute(
                select(LLMAnalysisRecord).where(
                    (LLMAnalysisRecord.target_type == task_type)
                    & (LLMAnalysisRecord.status == AnalysisStatus.PENDING.value)
                )
            )
        ).scalars().all()
        total = len(cnt)

    print(f"\n=== Layer '{task_type}': {total} pending tasks ===")
    i = 0
    while True:
        i += 1
        async with get_session() as session:
            # Pick the next pending record for this layer
            rec = (
                await session.execute(
                    select(LLMAnalysisRecord)
                    .where(
                        (LLMAnalysisRecord.target_type == task_type)
                        & (LLMAnalysisRecord.status == AnalysisStatus.PENDING.value)
                    )
                    .order_by(LLMAnalysisRecord.id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if not rec:
                break  # no more pending

            target_id = rec.target_id

            # Load target + build context while session is open
            if task_type == "file":
                target = (
                    await session.execute(select(File).where(File.id == target_id))
                ).scalar_one_or_none()
                if target is None:
                    await _mark_record_failed(rec, "file row missing")
                    skipped += 1
                    continue
                # Skip already-completed files (idempotency / duplicates)
                if target.analysis_status == AnalysisStatus.COMPLETED.value:
                    rec.status = AnalysisStatus.COMPLETED.value
                    skipped += 1
                    continue
                context = _file_context(target)
                rel_label = target.path
            elif task_type == "symbol":
                target = (
                    await session.execute(select(Symbol).where(Symbol.id == target_id))
                ).scalar_one_or_none()
                if target is None:
                    await _mark_record_failed(rec, "symbol row missing")
                    skipped += 1
                    continue
                file_record = (
                    await session.execute(select(File).where(File.id == target.file_id))
                ).scalar_one_or_none()
                context = _symbol_context(target, file_record)
                rel_label = target.qualified_name or target.name
            else:  # equation
                target = (
                    await session.execute(select(Equation).where(Equation.id == target_id))
                ).scalar_one_or_none()
                if target is None:
                    await _mark_record_failed(rec, "equation row missing")
                    skipped += 1
                    continue
                file_record = (
                    await session.execute(select(File).where(File.id == target.file_id))
                ).scalar_one_or_none()
                context = _equation_context(target, file_record)
                rel_label = target.name or "equation"

        # Call LLM OUTSIDE the db session so the LLM latency doesn't hold a lock
        result = await analyze_one(analyzer, prompt_name, context)
        status_ok = bool(result.result)

        # Persist results in a fresh session
        async with get_session() as session:
            rec2 = (
                await session.execute(
                    select(LLMAnalysisRecord).where(LLMAnalysisRecord.id == rec.id)
                )
            ).scalar_one_or_none()
            if rec2 is None:
                continue
            if status_ok:
                if task_type == "file":
                    t = (
                        await session.execute(select(File).where(File.id == target_id))
                    ).scalar_one_or_none()
                    if t is not None:
                        await _apply_file_result(t, result)
                elif task_type == "symbol":
                    t = (
                        await session.execute(select(Symbol).where(Symbol.id == target_id))
                    ).scalar_one_or_none()
                    if t is not None:
                        await _apply_symbol_result(t, result)
                else:
                    t = (
                        await session.execute(
                            select(Equation).where(Equation.id == target_id)
                        )
                    ).scalar_one_or_none()
                    if t is not None:
                        await _apply_equation_result(t, result)
                await _mark_record_completed(rec2, result)
                done += 1
            else:
                await _mark_record_failed(rec2, result.error or "analyze failed")
                failed += 1

        print(
            f"  [{i}/{total}] {'OK ' if status_ok else 'FAIL'} {task_type}: {rel_label}"
            + ("" if status_ok else f"  err={getattr(result, 'error', None)}"),
            flush=True,
        )

    print(f"  layer '{task_type}' -> done={done} failed={failed} skipped={skipped}")
    return done, failed, skipped


async def main() -> int:
    await init_db()
    analyzer = get_analyzer(mode="server_driven")
    if analyzer._client is None:
        print("ERROR: server_driven LLM client not initialized. Check config.")
        return 2

    t0 = time.time()
    total_done = total_failed = total_skipped = 0
    for layer in ("file", "symbol", "equation"):
        d, f, s = await run_layer(layer, analyzer)
        total_done += d
        total_failed += f
        total_skipped += s

    # Final coverage
    async with get_session() as session:
        for cls, label in [(File, "files"), (Symbol, "symbols"), (Equation, "equations")]:
            try:
                rows = (await session.execute(select(cls))).scalars().all()
                done_n = sum(
                    1 for r in rows
                    if getattr(r, "analysis_status", None) == AnalysisStatus.COMPLETED.value
                    or getattr(r, "llm_summary", None)
                )
                print(f"coverage {label}: {done_n}/{len(rows)} analyzed")
            except Exception as exc:
                print(f"coverage {label}: err {exc}")

    print(
        f"\nDONE in {time.time() - t0:.1f}s  "
        f"analyzed={total_done} failed={total_failed} skipped={total_skipped}"
    )
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
