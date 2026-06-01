"""RAG retriever over the O&M corpus (Chroma + MiniLM embeddings).

Grounds the Diagnostician and Work-order agents so they reference real procedure
and historically-observed faults rather than hallucinating. Persistent Chroma
collection; rebuilt idempotently from the knowledge corpus.
"""
from __future__ import annotations

import chromadb

from aeolus import config as C
from aeolus.agents import knowledge

_COLLECTION = "aeolus_om"
_client = None
_coll = None


def _get_collection():
    global _client, _coll
    if _coll is not None:
        return _coll
    _client = chromadb.PersistentClient(path=str(C.CHROMA_DIR))
    _coll = _client.get_or_create_collection(_COLLECTION)
    return _coll


def build_index(rebuild: bool = True) -> int:
    global _coll
    client = chromadb.PersistentClient(path=str(C.CHROMA_DIR))
    if rebuild:
        try:
            client.delete_collection(_COLLECTION)
        except Exception:
            pass
    _coll = client.get_or_create_collection(_COLLECTION)
    chunks = knowledge.build_corpus()
    _coll.add(
        ids=[c["id"] for c in chunks],
        documents=[c["text"] for c in chunks],
        metadatas=[{"source": c["source"], "component": c["component"],
                    "kind": c["kind"]} for c in chunks],
    )
    print(f"  RAG index built: {_coll.count()} chunks in Chroma ({C.CHROMA_DIR.name})")
    return _coll.count()


def search(query: str, k: int = 4, component: str | None = None) -> list[dict]:
    coll = _get_collection()
    if coll.count() == 0:
        build_index()
    kwargs = {"query_texts": [query], "n_results": k}
    res = coll.query(**kwargs)
    out = []
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0],
                               res["distances"][0]):
        out.append({"text": doc, "source": meta.get("source"),
                    "component": meta.get("component"),
                    "score": round(1.0 - dist, 3)})
    return out


if __name__ == "__main__":
    build_index()
    for r in search("main bearing temperature rising overheating", k=3):
        print(f"  [{r['score']}] {r['source']}: {r['text'][:80]}...")
