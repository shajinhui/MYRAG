"""
配置状态端点 —— 向前端暴露当前生效的 LLM / 嵌入提供商信息。
"""
from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/status")
async def get_config_status():
    """返回当前生效的提供商和模型名称，供界面展示。"""
    llm_provider = settings.LLM_PROVIDER.lower()

    if llm_provider == "ollama":
        llm_model = settings.OLLAMA_MODEL
    else:
        llm_model = settings.LLM_MODEL_FAST

    kg_provider = settings.KG_EMBEDDING_PROVIDER.lower()
    kg_model = settings.KG_EMBEDDING_MODEL

    return {
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "kg_embedding_provider": kg_provider,
        "kg_embedding_model": kg_model,
        "kg_embedding_dimension": settings.KG_EMBEDDING_DIMENSION,
        "myrag_embedding_model": settings.MYRAG_EMBEDDING_MODEL,
        "myrag_reranker_model": settings.MYRAG_RERANKER_MODEL,
    }
