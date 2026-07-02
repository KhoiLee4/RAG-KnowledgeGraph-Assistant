"""Chạy discover hàng loạt và (tùy chọn) điền expected_chunks vào questions_v2.json.

Ví dụ (từ thư mục backend):
  ..\\venv\\Scripts\\python.exe scripts\\discover_chunks.py
  ..\\venv\\Scripts\\python.exe scripts\\discover_chunks.py --write
  ..\\venv\\Scripts\\python.exe scripts\\discover_chunks.py --mode graph_rag
"""

from __future__ import annotations

import argparse
import json
import sys
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover chunks hàng loạt")
    parser.add_argument(
        "-d",
        "--dataset",
        default=str(BACKEND_ROOT / "evaluation" / "questions_v2.json"),
    )
    parser.add_argument("--mode", choices=["rag", "graph_rag"], default="rag")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Ghi top-1 chunk_id vào expected_chunks trong dataset",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=str(BACKEND_ROOT / "evaluation" / "discover_report.json"),
    )
    args = parser.parse_args()

    from app.evaluation.runner import EvaluationRunner, load_dataset

    dataset_path = Path(args.dataset)
    meta, items = load_dataset(dataset_path)
    collection = meta.get("collection_name")
    owner_id = meta.get("owner_id")

    runner = EvaluationRunner(collection_name=collection, owner_id=owner_id)
    report: list[dict] = []

    print(f"Dataset: {dataset_path}")
    print(f"Collection: {collection} | owner_id: {owner_id}")
    print(f"Mode: {args.mode} | write={args.write}\n")

    for i, item in enumerate(items, 1):
        if item.should_refuse:
            print(f"[{item.id}] SKIP (edge_case)")
            continue

        result = runner.run_retrieval(item.question, args.mode)
        chunks = result.get("retrieved_chunks") or []
        top_key = chunks[0]["chunk_key"] if chunks else ""

        row = {
            "id": item.id,
            "category": item.category,
            "question": item.question,
            "top_chunk_key": top_key,
            "top_file": chunks[0]["file_name"] if chunks else "",
            "top_score": chunks[0]["score"] if chunks else None,
            "all_chunks": [
                {
                    "chunk_key": c["chunk_key"],
                    "file_name": c["file_name"],
                    "score": c["score"],
                    "preview": c["text_preview"],
                }
                for c in chunks[:5]
            ],
        }
        report.append(row)

        status = top_key or "(khong co chunk)"
        print(f"[{item.id}] ({i}/{len(items)}) {status}")
        if chunks:
            print(f"       file={chunks[0]['file_name']} score={chunks[0]['score']}")
            print(f"       preview: {chunks[0]['text_preview'][:80]}...")

        if args.write and top_key:
            for q in meta["questions"]:
                if q["id"] == item.id:
                    q["expected_chunks"] = [{"chunk_id": top_key}]
                    break

    out_path = Path(args.output)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nBao cao: {out_path}")

    if args.write:
        dataset_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Da ghi expected_chunks (top-1) vao: {dataset_path}")
        print("Luu y: kiem tra lai top-1 co dung khong truoc khi chay benchmark!")
    else:
        print("Chua ghi vao dataset. Them --write de tu dong dien expected_chunks.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
