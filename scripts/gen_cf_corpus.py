"""Generate the CF parity corpus + golden top-k from the real SQLite MemoryDB.

The golden is FTS-only (``embedding_dims=0``) so it is reproducible without a
live embedder. The Vectorize/RRF fusion parity (Subsystem C) compares the
*fusion ordering* against a separately-computed RRF over deterministic fake
vectors, not this FTS golden.
"""

import json
import tempfile
from pathlib import Path

OUT = Path(__file__).parent.parent / "tests" / "fixtures"
QUERIES = [
    "python async",
    "vector search",
    "error handling",
    "rate limit",
    "user preference",
]


def build_corpus() -> list[dict]:
    cats = ["general", "fact", "preference", "skill", "decision"]
    templates = [
        "Define an async function {n} in Python with await and structured error handling.",
        "Vector search ranks embeddings by cosine similarity for memory {n}.",
        "Error handling: wrap the call in try/except and log the failure for {n}.",
        "Rate limit the loop to N requests per second to avoid 429 for {n}.",
        "User preference: keep concise replies in Vietnamese for {n}.",
    ]
    docs = []
    for ci in range(100):
        t = templates[ci % len(templates)]
        docs.append(
            {
                "content": t.format(n=f"item-{ci}"),
                "category": cats[ci % len(cats)],
                "tags": [f"tag{ci % 7}"],
                "source": f"src-{ci % 3}",
            }
        )
    return docs


def main():
    from mnemo_mcp.db import MemoryDB

    docs = build_corpus()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "cf_corpus.jsonl").write_text("\n".join(json.dumps(d) for d in docs))
    with tempfile.TemporaryDirectory() as tmp:
        db = MemoryDB(Path(tmp) / "baseline.db", embedding_dims=0)  # FTS-only golden
        for d in docs:
            db.add(
                d["content"], category=d["category"], tags=d["tags"], source=d["source"]
            )
        golden = {
            q: [r["content"][:40] for r in db.search(q, limit=10)] for q in QUERIES
        }
        (OUT / "cf_golden_topk.json").write_text(json.dumps(golden, indent=2))
        db.close()
    print(f"wrote {len(docs)} docs + golden for {len(QUERIES)} queries")


if __name__ == "__main__":
    main()
