"""Shared deterministic helpers for retrieval and compression eval runners."""

from __future__ import annotations

import logging
import shutil
import statistics
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from mnemo.db import MemoryDB


def quiet_eval_logs() -> None:
    """Silence per-row audit/migration noise during bulk benchmark CLI runs."""
    logger.disable("mnemo")
    logging.getLogger("alembic").setLevel(logging.WARNING)


def ensure_cached_dataset(
    url: str,
    cache_path: Path,
    *,
    timeout: float = 120.0,
) -> Path:
    """Return ``cache_path``, downloading from ``url`` when not cached."""
    if cache_path.is_file() and cache_path.stat().st_size > 0:
        return cache_path
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    with httpx.stream("GET", url, follow_redirects=True, timeout=timeout) as resp:
        resp.raise_for_status()
        with tmp_path.open("wb") as fh:
            for chunk in resp.iter_bytes():
                fh.write(chunk)
    tmp_path.replace(cache_path)
    return cache_path


def create_template_db(template_path: Path) -> Path:
    """Materialize one migrated empty SQLite store for fast per-case cloning."""
    if template_path.exists():
        template_path.unlink()
    db = MemoryDB(template_path, embedding_dims=0)
    db.close()
    return template_path


def open_cloned_db(template_path: Path, dest_path: Path) -> MemoryDB:
    """Clone ``template_path`` to ``dest_path`` and open a ``MemoryDB``."""
    if dest_path.exists():
        dest_path.unlink()
    shutil.copyfile(template_path, dest_path)
    return MemoryDB(dest_path, embedding_dims=0)


def chunk_text(text: str, max_len: int = 4200) -> list[str]:
    """Split text into chunks safely below ``MemoryDB.MAX_CONTENT_LENGTH``."""
    if len(text) <= max_len:
        return [text]
    return [text[i : i + max_len] for i in range(0, len(text), max_len)]


def summarize_latencies(latencies_ms: list[float]) -> dict[str, float]:
    """Compute p50, p95, and mean latencies in milliseconds."""
    if not latencies_ms:
        return {"p50": 0.0, "p95": 0.0, "mean": 0.0}
    ordered = sorted(latencies_ms)
    p95_idx = min(len(ordered) - 1, int(len(ordered) * 0.95))
    return {
        "p50": round(statistics.median(ordered), 3),
        "p95": round(ordered[p95_idx], 3),
        "mean": round(sum(ordered) / len(ordered), 3),
    }


async def llm_judge_retrieval(
    question: str,
    gold_answer: str,
    contexts: list[str],
) -> dict[str, Any]:
    """Judge whether retrieved ``contexts`` support answering ``question`` like ``gold_answer``.

    Requires an active ``[models.chat]`` cell via :func:`mnemo.llm.call_llm`.
    Raises ``RuntimeError`` when no usable chat credential is available so
    ``--with-llm-judge`` runs never silently fall back to synthetic passes.
    """
    from mnemo.llm import call_llm
    from mnemo.runtime import cell_configured, model_cell

    if not cell_configured("chat"):
        raise RuntimeError(
            "LLM judge requires [models.chat] configuration "
            "(set HULL_CHAT_API_KEY or configure ~/.mnemo/config.toml)"
        )

    context_block = "\n---\n".join(contexts[:5]) if contexts else "(empty)"
    prompt = (
        "You are a strict retrieval evaluator. Given a question, the reference "
        "answer, and the top retrieved memory snippets, decide whether the "
        "retrieved snippets contain the key facts needed to produce the "
        "reference answer.\n"
        "Respond on line 1 with EXACTLY 'VERDICT: YES' or 'VERDICT: NO', "
        "followed by a short 1-sentence justification.\n\n"
        f"Question: {question}\n"
        f"Reference answer: {gold_answer}\n"
        f"Retrieved contexts:\n{context_block}\n"
    )
    reply = await call_llm(prompt, temperature=0.0, max_tokens=120)
    if not reply or not reply.strip():
        raise RuntimeError(
            "LLM judge call returned empty response (check chat credential pool)"
        )
    first_line = reply.strip().splitlines()[0].upper()
    passed = "VERDICT: YES" in first_line
    return {
        "passed": passed,
        "model": model_cell("chat").model,
        "raw": reply.strip()[:240],
    }
