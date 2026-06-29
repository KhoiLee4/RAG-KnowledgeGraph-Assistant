"""Chạy benchmark RAG vs GraphRAG trên dataset JSON."""

from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.evaluation.metrics import (
    compute_retrieval_metrics,
    detect_refusal,
    keyword_overlap_score,
    retrieved_chunk_keys,
)
from app.services.chat_service import ChatService
from app.services.hybrid_retrieval_service import get_hybrid_retrieval_service


VALID_CATEGORIES = frozenset({
    "factual",
    "descriptive",
    "relationship",
    "combined",
    "edge_case",
})


@dataclass
class QuestionItem:
    id: str
    category: str
    question: str
    expected_chunks: list[dict[str, Any] | str] = field(default_factory=list)
    ground_truth: str = ""
    ground_truth_keywords: list[str] = field(default_factory=list)
    should_refuse: bool = False
    human_score: int | None = None
    notes: str = ""


def load_dataset(path: str | Path) -> tuple[dict[str, Any], list[QuestionItem]]:
    """Đọc file JSON benchmark."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items: list[QuestionItem] = []
    for q in raw.get("questions", []):
        category = str(q.get("category", "factual")).lower()
        if category not in VALID_CATEGORIES:
            category = "factual"
        items.append(
            QuestionItem(
                id=str(q.get("id", f"q{len(items)+1:02d}")),
                category=category,
                question=str(q["question"]),
                expected_chunks=q.get("expected_chunks") or [],
                ground_truth=str(q.get("ground_truth", "")),
                ground_truth_keywords=q.get("ground_truth_keywords") or [],
                should_refuse=bool(q.get("should_refuse", False)),
                human_score=q.get("human_score"),
                notes=str(q.get("notes", "")),
            )
        )
    return raw, items


class EvaluationRunner:
    """Benchmark retrieval + (tùy chọn) generation."""

    def __init__(
        self,
        collection_name: str | None = None,
        owner_id: str | None = None,
        top_k: int | None = None,
    ):
        self.collection_name = collection_name or settings.CHROMA_DEFAULT_COLLECTION
        self.owner_id = owner_id
        self.top_k = top_k or settings.RETRIEVAL_TOP_K
        self._hybrid = get_hybrid_retrieval_service()
        self._chat = ChatService()

    def run_retrieval(self, question: str, mode: str) -> dict[str, Any]:
        """Chỉ retrieval — không gọi Gemini generation."""
        t0 = time.perf_counter()
        bundle = self._hybrid.retrieve_all(
            query=question,
            collection_name=self.collection_name,
            owner_id=self.owner_id,
            n_results=self.top_k,
            retrieval_mode=mode,
        )
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        keys = retrieved_chunk_keys(bundle.vector_chunks)
        return {
            "retrieved_chunk_keys": keys,
            "retrieved_chunks": [
                {
                    "chunk_key": keys[i] if i < len(keys) else "",
                    "file_id": c.get("file_id", ""),
                    "file_name": c.get("file_name", ""),
                    "chunk_index": c.get("chunk_index", 0),
                    "score": c.get("score", c.get("combined_score", 0)),
                    "text_preview": str(c.get("text", ""))[:160],
                }
                for i, c in enumerate(bundle.vector_chunks)
            ],
            "query_type": bundle.query_type,
            "route": bundle.route,
            "sources_count": len(bundle.citations),
            "context_chars": len(bundle.context),
            "latency_ms": elapsed_ms,
        }

    def run_chat(self, question: str, mode: str) -> dict[str, Any]:
        """Full pipeline: retrieval + Gemini."""
        t0 = time.perf_counter()
        result = self._chat.chat(
            question=question,
            collection_name=self.collection_name,
            owner_id=self.owner_id,
            retrieval_mode=mode,
            n_context=self.top_k,
        )
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        return {
            "answer": result.get("answer", ""),
            "citations": result.get("citations", []),
            "sources_count": result.get("sources_count", 0),
            "context_used_chars": len(result.get("context_used", "") or ""),
            "latency_ms": elapsed_ms,
        }

    def evaluate_question(
        self,
        item: QuestionItem,
        mode: str,
        *,
        retrieval_only: bool = False,
        k: int = 5,
    ) -> dict[str, Any]:
        """Đánh giá một câu hỏi cho một retrieval mode."""
        retrieval = self.run_retrieval(item.question, mode)
        metrics = compute_retrieval_metrics(
            retrieval["retrieved_chunk_keys"],
            item.expected_chunks,
            k=k,
        )

        out: dict[str, Any] = {
            "question_id": item.id,
            "category": item.category,
            "mode": mode,
            "question": item.question,
            "retrieval": retrieval,
            "retrieval_metrics": metrics,
        }

        if retrieval_only:
            return out

        chat = self.run_chat(item.question, mode)
        answer = chat["answer"]
        refused = detect_refusal(answer)
        kw_score = keyword_overlap_score(answer, item.ground_truth_keywords)

        refusal_correct: bool | None = None
        if item.should_refuse:
            refusal_correct = refused
        elif item.category == "edge_case" and item.expected_chunks:
            refusal_correct = refused

        out["generation"] = chat
        out["answer_metrics"] = {
            "refused": refused,
            "refusal_correct": refusal_correct,
            "keyword_overlap": kw_score,
            "human_score": item.human_score,
            "citations_count": chat["sources_count"],
        }
        return out

    def run_benchmark(
        self,
        items: list[QuestionItem],
        modes: list[str],
        *,
        retrieval_only: bool = False,
        k: int = 5,
    ) -> dict[str, Any]:
        """Chạy toàn bộ dataset."""
        results: list[dict[str, Any]] = []
        for item in items:
            for mode in modes:
                results.append(
                    self.evaluate_question(
                        item,
                        mode,
                        retrieval_only=retrieval_only,
                        k=k,
                    )
                )

        return {
            "summary": summarize_results(results, modes),
            "by_category": summarize_by_category(results, modes),
            "results": results,
        }


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def summarize_results(results: list[dict[str, Any]], modes: list[str]) -> dict[str, Any]:
    """Tổng hợp metric trung bình theo mode."""
    summary: dict[str, Any] = {}
    for mode in modes:
        mode_rows = [r for r in results if r["mode"] == mode]
        retrieval_rows = [
            r["retrieval_metrics"]
            for r in mode_rows
            if not r["retrieval_metrics"].get("skipped")
        ]

        summary[mode] = {
            "questions": len(mode_rows),
            "retrieval": {
                "evaluated": len(retrieval_rows),
                "hit_at_k": _avg([m["hit_at_k"] for m in retrieval_rows if m["hit_at_k"] is not None]),
                "recall_at_k": _avg([m["recall_at_k"] for m in retrieval_rows if m["recall_at_k"] is not None]),
                "precision_at_k": _avg([m["precision_at_k"] for m in retrieval_rows if m["precision_at_k"] is not None]),
                "mrr": _avg([m["mrr"] for m in retrieval_rows if m["mrr"] is not None]),
            },
            "answer": _summarize_answer_metrics(mode_rows),
        }
    return summary


def _summarize_answer_metrics(mode_rows: list[dict[str, Any]]) -> dict[str, Any]:
    gen_rows = [r for r in mode_rows if "answer_metrics" in r]
    if not gen_rows:
        return {}

    human_scores = [
        r["answer_metrics"]["human_score"]
        for r in gen_rows
        if r["answer_metrics"].get("human_score") is not None
    ]
    kw_scores = [
        r["answer_metrics"]["keyword_overlap"]
        for r in gen_rows
        if r["answer_metrics"].get("keyword_overlap") is not None
    ]
    refusal_rows = [
        r["answer_metrics"]["refusal_correct"]
        for r in gen_rows
        if r["answer_metrics"].get("refusal_correct") is not None
    ]

    return {
        "human_score_total": sum(human_scores) if human_scores else None,
        "human_score_max": len(human_scores) * 2 if human_scores else None,
        "human_score_avg": _avg([float(s) for s in human_scores]),
        "keyword_overlap_avg": _avg([float(s) for s in kw_scores]),
        "refusal_accuracy": _avg([1.0 if x else 0.0 for x in refusal_rows]),
        "refusal_evaluated": len(refusal_rows),
    }


def summarize_by_category(
    results: list[dict[str, Any]],
    modes: list[str],
) -> dict[str, Any]:
    """Bảng kết quả theo nhóm câu hỏi (Lớp 4)."""
    table: dict[str, Any] = {}
    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        by_cat[row["category"]].append(row)

    for category, rows in sorted(by_cat.items()):
        table[category] = {}
        for mode in modes:
            mode_rows = [r for r in rows if r["mode"] == mode]
            retrieval_rows = [
                r["retrieval_metrics"]
                for r in mode_rows
                if not r["retrieval_metrics"].get("skipped")
            ]
            answer = _summarize_answer_metrics(mode_rows)
            table[category][mode] = {
                "count": len(mode_rows),
                "hit_at_k": _avg([m["hit_at_k"] for m in retrieval_rows if m["hit_at_k"] is not None]),
                "mrr": _avg([m["mrr"] for m in retrieval_rows if m["mrr"] is not None]),
                "human_score_total": answer.get("human_score_total"),
                "human_score_max": answer.get("human_score_max"),
                "keyword_overlap_avg": answer.get("keyword_overlap_avg"),
                "refusal_accuracy": answer.get("refusal_accuracy"),
            }
    return table
