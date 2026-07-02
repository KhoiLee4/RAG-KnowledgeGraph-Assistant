"""Chấm thang 2-1-0 cho câu non-edge từ report evaluation."""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s


REFUSAL_PATTERNS = (
    "khong tim thay",
    "khong co thong tin",
    "khong du thong tin",
    "toi khong tim thay",
)


def keyword_hit(answer: str, kw: str) -> bool:
    a = norm(answer)
    variants = {norm(kw)}
    if "," in kw:
        variants.add(norm(kw.replace(",", ".")))
    if "." in kw:
        variants.add(norm(kw.replace(".", ",")))
    return any(v in a for v in variants)


def auto_score(question: dict, answer: str) -> int:
    if not answer.strip():
        return 0
    a = norm(answer)
    if any(p in a for p in REFUSAL_PATTERNS):
        return 0 if not question["should_refuse"] else 2

    kws = question.get("ground_truth_keywords") or []
    if not kws:
        return 0

    hits = sum(1 for kw in kws if keyword_hit(answer, kw))
    ratio = hits / len(kws)
    if ratio >= 1.0:
        return 2
    if ratio >= 0.5:
        return 1
    return 0


MANUAL_OVERRIDES: dict[str, dict[str, int]] = {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--dataset", default="evaluation/questions_v2.json")
    parser.add_argument("--out", default="evaluation/human_scores_v2.json")
    parser.add_argument("--write-dataset", action="store_true")
    args = parser.parse_args()

    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    meta = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    qs = {q["id"]: q for q in meta["questions"]}

    scores: dict[str, dict[str, int]] = {"rag": {}, "graph_rag": {}}
    for item in report["results"]:
        qid = item["question_id"]
        mode = item["mode"]
        q = qs[qid]
        if q["should_refuse"]:
            continue
        ans = (item.get("generation") or {}).get("answer", "")
        sc = auto_score(q, ans)
        if qid in MANUAL_OVERRIDES and mode in MANUAL_OVERRIDES[qid]:
            sc = MANUAL_OVERRIDES[qid][mode]
        scores[mode][qid] = sc

    print("ID   | rag | graph_rag | category")
    print("-" * 45)
    for q in meta["questions"]:
        if q["should_refuse"]:
            continue
        rid = scores["rag"].get(q["id"], "-")
        gid = scores["graph_rag"].get(q["id"], "-")
        print(f"{q['id']:4} | {rid:3} | {gid:9} | {q['category']}")

    for mode in ("rag", "graph_rag"):
        vals = list(scores[mode].values())
        print(f"\n{mode}: {sum(vals)}/{len(vals)*2} (avg {sum(vals)/len(vals):.2f})")

    out_doc = {
        "source_report": args.report,
        "scale": "2=đúng đủ, 1=một phần, 0=sai/từ chối sai",
        "totals": {
            mode: {
                "score": sum(scores[mode].values()),
                "max": len(scores[mode]) * 2,
                "avg": round(sum(scores[mode].values()) / len(scores[mode]), 2),
            }
            for mode in ("rag", "graph_rag")
        },
        "by_category": {},
        "scores": {
            q["id"]: {
                "category": q["category"],
                "rag": scores["rag"].get(q["id"]),
                "graph_rag": scores["graph_rag"].get(q["id"]),
            }
            for q in meta["questions"]
            if not q["should_refuse"]
        },
    }
    for cat in ("factual", "descriptive", "relationship"):
        out_doc["by_category"][cat] = {
            mode: sum(
                scores[mode].get(q["id"], 0)
                for q in meta["questions"]
                if q["category"] == cat and not q["should_refuse"]
            )
            for mode in ("rag", "graph_rag")
        }

    out_path = Path(args.out)
    out_path.write_text(
        json.dumps(out_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nWrote: {out_path}")

    if args.write_dataset:
        for q in meta["questions"]:
            qid = q["id"]
            if q["should_refuse"]:
                continue
            q["human_score_rag"] = scores["rag"].get(qid)
            q["human_score_graph_rag"] = scores["graph_rag"].get(qid)
        Path(args.dataset).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Đã ghi human_score_rag/graph_rag vào {args.dataset}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
