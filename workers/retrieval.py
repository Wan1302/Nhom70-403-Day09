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
import hashlib
import math
import re
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

_EMBEDDING_FN = None
STOPWORDS = {
    "a", "an", "and", "are", "for", "how", "is", "of", "the", "to", "what",
    "ai", "bao", "bi", "biết", "có", "của", "được", "gì", "không", "là",
    "lâu", "mấy", "nào", "như", "theo", "thì", "trong", "và", "vì",
}
IMPORTANT_TERMS = {
    "access", "escalation", "flash", "level", "license", "p1", "policy",
    "refund", "sale", "sla", "subscription", "ticket",
}


def _tokenize(text: str) -> set:
    return {
        token
        for token in re.findall(r"\w+", text.lower(), flags=re.UNICODE)
        if token not in STOPWORDS and len(token) > 1
    }


def _hash_embedding(text: str, dim: int = 384) -> list:
    """Deterministic local embedding fallback when external embedders are unavailable."""
    vector = [0.0] * dim
    tokens = re.findall(r"\w+", text.lower(), flags=re.UNICODE)
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[idx] += sign

    norm = math.sqrt(sum(v * v for v in vector))
    if not norm:
        return vector
    return [v / norm for v in vector]


def _load_docs(docs_dir: Path = DEFAULT_DOCS_DIR) -> list:
    docs = []
    if not docs_dir.exists():
        return docs

    for path in sorted(docs_dir.glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        docs.append({
            "id": path.stem,
            "text": text,
            "source": path.name,
            "metadata": {"source": path.name, "path": str(path)},
        })
    return docs


def _fallback_keyword_search(query: str, top_k: int = DEFAULT_TOP_K) -> list:
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    ranked = []
    for doc in _load_docs():
        doc_tokens = _tokenize(doc["text"])
        overlap = query_tokens & doc_tokens
        if not overlap:
            continue

        score = sum(3 if token in IMPORTANT_TERMS else 1 for token in overlap)
        score = score / max(sum(3 if token in IMPORTANT_TERMS else 1 for token in query_tokens), 1)
        source = doc["source"].lower()
        if {"sla", "p1", "ticket"} & query_tokens and "sla" in source:
            score += 0.5
        if {"refund", "flash", "sale", "license", "subscription", "policy"} & query_tokens and "refund" in source:
            score += 0.5
        if {"access", "level"} & query_tokens and "access" in source:
            score += 0.5
        metadata = dict(doc["metadata"])
        metadata["retrieval"] = "keyword_fallback"
        ranked.append({
            "text": doc["text"],
            "source": doc["source"],
            "score": round(min(score, 1.0), 4),
            "metadata": metadata,
        })

    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[:top_k]


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
        model = SentenceTransformer("all-MiniLM-L6-v2")
        def embed(text: str) -> list:
            return model.encode([text])[0].tolist()
        _EMBEDDING_FN = embed
        return _EMBEDDING_FN
    except Exception as e:
        print(f"WARNING: SentenceTransformer unavailable, using local fallback: {e}")

    # Option B: OpenAI (cần API key)
    # Local-only retrieval: do not call OpenAI for embeddings.

    # Fallback: random embeddings cho test (KHÔNG dùng production)
    def embed(text: str) -> list:
        return _hash_embedding(text)
    print("WARNING: Using deterministic local embeddings (test only). Install sentence-transformers.")
    _EMBEDDING_FN = embed
    return _EMBEDDING_FN


def _ensure_collection_has_docs(collection, embed) -> None:
    try:
        if collection.count() > 0:
            return
    except Exception:
        return

    docs = _load_docs()
    if not docs:
        print(f"WARNING: No documents found in {DEFAULT_DOCS_DIR}")
        return

    embeddings = [embed(doc["text"]) for doc in docs]
    collection.upsert(
        ids=[doc["id"] for doc in docs],
        documents=[doc["text"] for doc in docs],
        metadatas=[doc["metadata"] for doc in docs],
        embeddings=embeddings,
    )
    print(f"Indexed {len(docs)} docs into Chroma collection '{CHROMA_COLLECTION}'.")


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
    if embed is not None:
        _ensure_collection_has_docs(collection, embed)
    return collection


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
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "distances", "metadatas"]
        )

        chunks = []
        documents = results.get("documents", [[]])[0] or []
        distances = results.get("distances", [[]])[0] or []
        metadatas = results.get("metadatas", [[]])[0] or []

        for i, (doc, dist, meta) in enumerate(zip(documents, distances, metadatas)):
            meta = meta or {}
            score = max(0.0, min(1.0, 1 - float(dist)))
            chunks.append({
                "text": doc,
                "source": meta.get("source", "unknown"),
                "score": round(score, 4),  # cosine similarity
                "metadata": meta,
            })
        if chunks:
            return chunks

        return _fallback_keyword_search(query, top_k=top_k)

    except Exception as e:
        print(f"WARNING: ChromaDB query failed: {e}")
        # Fallback: return empty (abstain)
        return _fallback_keyword_search(query, top_k=top_k)


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

        worker_io["output"] = {
            "chunks_count": len(chunks),
            "sources": sources,
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
