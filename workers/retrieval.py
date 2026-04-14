"""
workers/retrieval.py — Retrieval Worker
Sprint 2: Implement retrieval từ ChromaDB, trả về chunks + sources.

Input (từ AgentState):
    - task: câu hỏi cần retrieve
    - (optional) retrieved_chunks nếu đã có từ trước

Output (vào AgentState):
    - retrieved_chunks: list of {"text", "source", "score", "metadata"}
    - retrieved_sources: list of source filenames
    - worker_io_log: log input/output của worker này

Gọi độc lập để test:
    python workers/retrieval.py
"""

import os
import sys
from pathlib import Path

# ─────────────────────────────────────────────
# Worker Contract (xem contracts/worker_contracts.yaml)
# Input:  {"task": str, "top_k": int = 3}
# Output: {"retrieved_chunks": list, "retrieved_sources": list, "error": dict | None}
# ─────────────────────────────────────────────

WORKER_NAME = "retrieval_worker"
DEFAULT_TOP_K = 3
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOCS_DIR = REPO_ROOT / "data" / "docs"

try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except Exception:
    pass

CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", str(REPO_ROOT / "chroma_db"))
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "day09_docs")
CHROMA_SPACE = os.getenv("CHROMA_SPACE")

_EMBEDDING_FN = None


def _get_embedding_fn():
    """
    Trả về embedding function.
    TODO Sprint 1: Implement dùng OpenAI hoặc Sentence Transformers.
    """
    # Option A: Sentence Transformers (offline, không cần API key)
    global _EMBEDDING_FN
    if _EMBEDDING_FN is not None:
        return _EMBEDDING_FN

    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2", local_files_only=True)
        def embed(text: str) -> list:
            return model.encode([text])[0].tolist()
        _EMBEDDING_FN = embed
        return _EMBEDDING_FN
    except Exception as e:
        raise RuntimeError(f"SentenceTransformer embedding model unavailable: {e}") from e


def _get_collection(embed=None):
    """
    Kết nối ChromaDB collection.
    TODO Sprint 2: Đảm bảo collection đã được build từ Step 3 trong README.
    """
    import chromadb
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    try:
        collection = client.get_collection(CHROMA_COLLECTION)
    except Exception:
        # Auto-create nếu chưa có
        collection = client.get_or_create_collection(
            CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"}
        )
        print(f"WARNING: Collection '{CHROMA_COLLECTION}' did not exist; created it.")
    return collection


def _collection_space(collection) -> str:
    """Trả về metric của Chroma collection để convert distance đúng."""
    metadata = getattr(collection, "metadata", None) or {}
    return (metadata.get("hnsw:space") or CHROMA_SPACE or "l2").lower()


def _distance_to_score(distance: float, space: str) -> float:
    """Convert Chroma distance thành relevance score trong khoảng 0..1."""
    if space == "cosine":
        # Chroma cosine distance thường là 1 - cosine_similarity.
        return max(0.0, min(1.0, 1.0 - distance))
    if space == "l2":
        # L2 distance không nằm trong [0, 1], nên dùng hàm giảm đơn điệu.
        return 1.0 / (1.0 + max(distance, 0.0))
    if space == "ip":
        # Inner-product distance trong Chroma cũng là distance càng nhỏ càng gần.
        return max(0.0, min(1.0, 1.0 - distance))
    return max(0.0, min(1.0, 1.0 - distance))


def retrieve_dense(query: str, top_k: int = DEFAULT_TOP_K) -> list:
    """
    Dense retrieval: embed query → query ChromaDB → trả về top_k chunks.

    TODO Sprint 2: Implement phần này.
    - Dùng _get_embedding_fn() để embed query
    - Query collection với n_results=top_k
    - Format result thành list of dict

    Returns:
        list of {"text": str, "source": str, "score": float, "metadata": dict}
    """
    # TODO: Implement dense retrieval
    if not query:
        return []

    try:
        embed = _get_embedding_fn()
        query_embedding = embed(query)
        collection = _get_collection(embed=embed)
        distance_metric = _collection_space(collection)
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "distances", "metadatas"]
        )

        chunks = []
        documents = results.get("documents", [[]])[0] or []
        distances = results.get("distances", [[]])[0] or []
        metadatas = results.get("metadatas", [[]])[0] or []

        for doc, dist, meta in zip(documents, distances, metadatas):
            meta = meta or {}
            distance = float(dist)
            score = _distance_to_score(distance, distance_metric)
            meta = dict(meta)
            meta["distance"] = round(distance, 4)
            meta["distance_metric"] = distance_metric
            chunks.append({
                "text": doc,
                "source": meta.get("source", "unknown"),
                "score": round(score, 4),
                "metadata": meta,
            })
        if chunks:
            return chunks

        return []

    except Exception as e:
        # Fallback: return empty (abstain)
        raise RuntimeError(f"ChromaDB query failed: {e}") from e


def run(state: dict) -> dict:
    """
    Worker entry point — gọi từ graph.py.

    Args:
        state: AgentState dict

    Returns:
        Updated AgentState với retrieved_chunks và retrieved_sources
    """
    task = state.get("task", "")
    top_k = state.get("top_k", state.get("retrieval_top_k", DEFAULT_TOP_K))

    state.setdefault("workers_called", [])
    state.setdefault("history", [])

    state["workers_called"].append(WORKER_NAME)

    # Log worker IO (theo contract)
    worker_io = {
        "worker": WORKER_NAME,
        "input": {"task": task, "top_k": top_k},
        "output": None,
        "error": None,
    }

    try:
        chunks = retrieve_dense(task, top_k=top_k)

        sources = list(dict.fromkeys(c["source"] for c in chunks))

        state["retrieved_chunks"] = chunks
        state["retrieved_sources"] = sources
        scores = [c.get("score", 0) for c in chunks]
        distance_metrics = list(dict.fromkeys(
            c.get("metadata", {}).get("distance_metric") for c in chunks
            if c.get("metadata", {}).get("distance_metric")
        ))

        worker_io["output"] = {
            "chunks_count": len(chunks),
            "sources": sources,
            "score_range": [min(scores), max(scores)] if scores else [],
            "distance_metrics": distance_metrics,
        }
        state["history"].append(
            f"[{WORKER_NAME}] retrieved {len(chunks)} chunks from {sources}"
        )

    except Exception as e:
        worker_io["error"] = {"code": "RETRIEVAL_FAILED", "reason": str(e)}
        state["retrieved_chunks"] = []
        state["retrieved_sources"] = []
        state["history"].append(f"[{WORKER_NAME}] ERROR: {e}")

    # Ghi worker IO vào state để trace
    state.setdefault("worker_io_logs", []).append(worker_io)

    return state


# ─────────────────────────────────────────────
# Test độc lập
# ─────────────────────────────────────────────

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 50)
    print("Retrieval Worker — Standalone Test")
    print("=" * 50)

    test_queries = [
        "SLA ticket P1 là bao lâu?",
        "Điều kiện được hoàn tiền là gì?",
        "Ai phê duyệt cấp quyền Level 3?",
    ]

    for query in test_queries:
        print(f"\n▶ Query: {query}")
        result = run({"task": query})
        chunks = result.get("retrieved_chunks", [])
        print(f"  Retrieved: {len(chunks)} chunks")
        for c in chunks[:2]:
            print(f"    [{c['score']:.3f}] {c['source']}: {c['text'][:80]}...")
        print(f"  Sources: {result.get('retrieved_sources', [])}")

    print("\n✅ retrieval_worker test done.")
