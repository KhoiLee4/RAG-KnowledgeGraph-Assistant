"""CLI đánh giá RAG / GraphRAG.

Ví dụ (từ thư mục backend, dùng venv):

  ..\\venv\\Scripts\\python.exe scripts\\evaluate.py --indexing-stats
  ..\\venv\\Scripts\\python.exe scripts\\evaluate.py discover -q "GraphRAG là gì?"
  ..\\venv\\Scripts\\python.exe scripts\\evaluate.py run --retrieval-only
  ..\\venv\\Scripts\\python.exe scripts\\evaluate.py run --modes rag graph_rag
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from dotenv import load_dotenv  # noqa: E402

from app.core.config import ENV_FILE_PATH  # noqa: E402

load_dotenv(ENV_FILE_PATH)


def _default_dataset() -> Path:
    return BACKEND_ROOT / "evaluation" / "questions.json"


def _default_output_dir() -> Path:
    return BACKEND_ROOT / "evaluation" / "results"


def _dataset_defaults(dataset_path: Path | None = None) -> dict[str, str | None]:
    """Đọc collection_name / owner_id từ questions.json (nếu có)."""
    path = dataset_path or _default_dataset()
    if not path.is_file():
        return {"collection_name": None, "owner_id": None}
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
        return {
            "collection_name": meta.get("collection_name"),
            "owner_id": meta.get("owner_id"),
        }
    except (json.JSONDecodeError, OSError):
        return {"collection_name": None, "owner_id": None}


def _resolve_collection_owner(
    collection: str | None,
    owner_id: str | None,
    dataset_path: Path | None = None,
) -> tuple[str | None, str | None]:
    defaults = _dataset_defaults(dataset_path)
    return (
        collection or defaults.get("collection_name"),
        owner_id or defaults.get("owner_id"),
    )


def cmd_indexing_stats(args: argparse.Namespace) -> int:
    from app.evaluation.indexing_stats import collect_indexing_stats

    collection, owner_id = _resolve_collection_owner(args.collection, args.owner_id)
    stats = collect_indexing_stats(
        owner_id=owner_id,
        collection_name=collection,
    )
    text = json.dumps(stats, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Đã ghi: {args.output}")
    else:
        print(text)
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    from app.evaluation.runner import EvaluationRunner

    collection, owner_id = _resolve_collection_owner(args.collection, args.owner_id)
    if not collection:
        print(
            "Cảnh báo: chưa có collection — đặt collection_name trong "
            "evaluation/questions.json hoặc dùng --collection kb_...",
            file=sys.stderr,
        )

    runner = EvaluationRunner(
        collection_name=collection,
        owner_id=owner_id,
        top_k=args.top_k,
    )
    result = runner.run_retrieval(args.question, args.mode)
    print(f"\nCâu hỏi: {args.question}")
    print(f"Collection: {collection or '(default)'} | owner_id: {owner_id or '(none)'}")
    print(f"Mode: {args.mode} | route: {result['route']} | query_type: {result['query_type']}")
    print(f"Top-{args.top_k} chunks ({result['latency_ms']} ms):\n")
    if not result["retrieved_chunks"]:
        print(
            "  (không có chunk — kiểm tra collection trong questions.json "
            "hoặc giảm RETRIEVAL_MIN_SCORE trong .env)\n"
        )
    for i, chunk in enumerate(result["retrieved_chunks"], 1):
        print(f"  {i}. {chunk['chunk_key']}")
        print(f"     {chunk['file_name']} | score={chunk['score']}")
        print(f"     {chunk['text_preview']}...")
        print()
    print("Copy chunk_key vào expected_chunks trong evaluation/questions.json:")
    print(json.dumps(
        [{"chunk_id": c["chunk_key"]} for c in result["retrieved_chunks"][:3]],
        ensure_ascii=False,
        indent=2,
    ))
    return 0


def _print_summary_table(report: dict) -> None:
    print("\n=== TỔNG HỢP THEO MODE ===")
    for mode, data in report.get("summary", {}).items():
        ret = data.get("retrieval", {})
        ans = data.get("answer", {})
        print(f"\n[{mode}]")
        if ret.get("evaluated"):
            print(
                f"  Retrieval (n={ret['evaluated']}): "
                f"Hit@k={ret.get('hit_at_k')} | "
                f"Recall@k={ret.get('recall_at_k')} | "
                f"MRR={ret.get('mrr')}"
            )
        else:
            print("  Retrieval: chưa có expected_chunks — bỏ qua metric IR")
        if ans:
            if ans.get("human_score_total") is not None:
                print(
                    f"  Human score: {ans['human_score_total']}/{ans['human_score_max']} "
                    f"(avg {ans.get('human_score_avg')})"
                )
            if ans.get("keyword_overlap_avg") is not None:
                print(f"  Keyword overlap avg: {ans['keyword_overlap_avg']}")
            if ans.get("refusal_evaluated"):
                print(f"  Refusal accuracy: {ans.get('refusal_accuracy')}")

    print("\n=== THEO NHÓM CÂU HỎI ===")
    header = f"{'Nhóm':<14} {'Mode':<12} {'Hit@k':>6} {'MRR':>6} {'Điểm':>10} {'KW-ovlp':>8}"
    print(header)
    print("-" * len(header))
    for category, modes in report.get("by_category", {}).items():
        for mode, row in modes.items():
            score = ""
            if row.get("human_score_total") is not None:
                score = f"{row['human_score_total']}/{row['human_score_max']}"
            print(
                f"{category:<14} {mode:<12} "
                f"{_fmt(row.get('hit_at_k')):>6} "
                f"{_fmt(row.get('mrr')):>6} "
                f"{score:>10} "
                f"{_fmt(row.get('keyword_overlap_avg')):>8}"
            )


def _fmt(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def cmd_run(args: argparse.Namespace) -> int:
    from app.evaluation.runner import EvaluationRunner, load_dataset

    dataset_path = Path(args.dataset)
    if not dataset_path.is_file():
        print(f"Không tìm thấy dataset: {dataset_path}", file=sys.stderr)
        return 1

    meta, items = load_dataset(dataset_path)
    collection = args.collection or meta.get("collection_name")
    owner_id = args.owner_id or meta.get("owner_id")

    runner = EvaluationRunner(
        collection_name=collection,
        owner_id=owner_id,
        top_k=args.top_k,
    )

    print(f"Dataset: {dataset_path} ({len(items)} câu)")
    print(f"Collection: {collection or '(default)'} | owner_id: {owner_id or '(none)'}")
    print(f"Modes: {args.modes} | retrieval_only={args.retrieval_only}")

    report = runner.run_benchmark(
        items,
        modes=args.modes,
        retrieval_only=args.retrieval_only,
        k=args.top_k,
    )
    report["meta"] = {
        "dataset": str(dataset_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "collection_name": collection,
        "owner_id": owner_id,
        "modes": args.modes,
        "retrieval_only": args.retrieval_only,
        "top_k": args.top_k,
    }

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"report_{stamp}.json"
    out_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    _print_summary_table(report)
    print(f"\nBáo cáo chi tiết: {out_file}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Đánh giá RAG / GraphRAG")
    sub = parser.add_subparsers(dest="command", required=True)

    p_stats = sub.add_parser("indexing-stats", help="Lớp 1: thống kê indexing")
    p_stats.add_argument("--owner-id", default=None)
    p_stats.add_argument("--collection", default=None)
    p_stats.add_argument("--output", "-o", default=None)
    p_stats.set_defaults(func=cmd_indexing_stats)

    p_disc = sub.add_parser("discover", help="Xem top chunks cho một câu hỏi")
    p_disc.add_argument("--question", "-q", required=True)
    p_disc.add_argument("--mode", choices=["rag", "graph_rag"], default="rag")
    p_disc.add_argument("--owner-id", default=None)
    p_disc.add_argument("--collection", default=None)
    p_disc.add_argument("--top-k", type=int, default=5)
    p_disc.set_defaults(func=cmd_discover)

    p_run = sub.add_parser("run", help="Chạy benchmark dataset")
    p_run.add_argument("--dataset", "-d", default=str(_default_dataset()))
    p_run.add_argument("--modes", nargs="+", choices=["rag", "graph_rag"], default=["rag", "graph_rag"])
    p_run.add_argument("--owner-id", default=None)
    p_run.add_argument("--collection", default=None)
    p_run.add_argument("--top-k", type=int, default=5)
    p_run.add_argument("--retrieval-only", action="store_true", help="Không gọi Gemini")
    p_run.add_argument("--output-dir", default=str(_default_output_dir()))
    p_run.set_defaults(func=cmd_run)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
