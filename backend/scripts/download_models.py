"""预下载 sentence-transformers 模型，用于离线使用。

用法：
    python backend/scripts/download_models.py

环境变量（可选）：
    MYRAG_EMBEDDING_MODEL  —— 默认：BAAI/bge-m3
    MYRAG_RERANKER_MODEL   —— 默认：BAAI/bge-reranker-v2-m3
"""
import os
import sys


def download_models():
    embedding_model = os.environ.get("MYRAG_EMBEDDING_MODEL", "BAAI/bge-m3")
    reranker_model = os.environ.get("MYRAG_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")

    from sentence_transformers import SentenceTransformer, CrossEncoder

    print(f"[1/2] Downloading embedding model: {embedding_model}")
    SentenceTransformer(embedding_model)
    print(f"      Done.")

    print(f"[2/2] Downloading reranker model: {reranker_model}")
    CrossEncoder(reranker_model)
    print(f"      Done.")

    print("\nAll models downloaded successfully.")


if __name__ == "__main__":
    download_models()
