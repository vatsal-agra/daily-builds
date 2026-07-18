"""Ranking-quality evaluation: given hand-labeled relevance judgments
(query -> the doc_ids that are actually relevant), compute Precision@K
and NDCG@K against an Engine's real BM25 output. This measures ranking
quality quantitatively instead of eyeballing whether results "look
reasonable" — the same technique real IR systems (TREC-style
evaluation) use, applied here to Trove's own demo corpus."""

import json
import math
import os

DEFAULT_JUDGMENTS_PATH = os.path.join(os.path.dirname(__file__), "default_judgments.json")


def load_judgments(path=None):
    path = path or DEFAULT_JUDGMENTS_PATH
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return {query: set(doc_ids) for query, doc_ids in raw.items()}


def precision_at_k(retrieved, relevant, k):
    top_k = retrieved[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for d in top_k if d in relevant)
    return hits / len(top_k)


def _dcg(relevances):
    return sum(rel / math.log2(i + 1) for i, rel in enumerate(relevances, start=1))


def ndcg_at_k(retrieved, relevant, k):
    top_k = retrieved[:k]
    relevances = [1.0 if d in relevant else 0.0 for d in top_k]
    dcg = _dcg(relevances)
    ideal = [1.0] * min(len(relevant), k) + [0.0] * max(0, k - len(relevant))
    idcg = _dcg(ideal)
    return dcg / idcg if idcg > 0 else 0.0


def evaluate_query(engine, query_text, relevant, k=5):
    outcome = engine.search(query_text, top=k)
    retrieved = [r.doc_id for r in outcome["results"]]
    return {
        "query": query_text,
        "retrieved": retrieved,
        "relevant": sorted(relevant),
        "precision_at_k": precision_at_k(retrieved, relevant, k),
        "ndcg_at_k": ndcg_at_k(retrieved, relevant, k),
    }


def run_eval(engine, judgments_path=None, k=5, out=print):
    judgments = load_judgments(judgments_path)
    if not judgments:
        out("no judgments to evaluate")
        return 1

    rows = [evaluate_query(engine, q, rel, k) for q, rel in judgments.items()]

    out(f"{'query':32} {'P@' + str(k):>6} {'NDCG@' + str(k):>8}   retrieved (top {k})")
    out("-" * 90)
    for row in rows:
        retrieved_str = ", ".join(row["retrieved"]) if row["retrieved"] else "(none)"
        out(f"{row['query'][:32]:32} {row['precision_at_k']:6.2f} {row['ndcg_at_k']:8.2f}   {retrieved_str}")

    avg_p = sum(r["precision_at_k"] for r in rows) / len(rows)
    avg_ndcg = sum(r["ndcg_at_k"] for r in rows) / len(rows)
    out("-" * 90)
    out(f"{'MEAN':32} {avg_p:6.2f} {avg_ndcg:8.2f}   ({len(rows)} queries)")
    return 0
