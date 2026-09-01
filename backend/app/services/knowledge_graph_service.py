"""
知识图谱服务
========================

基于 LightRAG 的按工作区知识图谱，支持可配置的 LLM 与向量化。
使用文件存储（NetworkX 图 + NanoVectorDB）——无需额外的 Docker 服务。

用法：
    kg = KnowledgeGraphService(workspace_id=1)
    await kg.ingest("来自文档的 markdown 文本...")
    result = await kg.query("主要主题是什么？", mode="hybrid")
    await kg.cleanup()
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

import numpy as np

from app.core.config import settings
from app.services.llm import get_embedding_provider, get_llm_provider
from app.services.llm.types import LLMMessage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 面向 LightRAG 的提供商适配器
# ---------------------------------------------------------------------------

async def _kg_llm_complete(
    prompt: str,
    system_prompt: Optional[str] = None,
    history_messages: Optional[list] = None,
    keyword_extraction: bool = False,
    **kwargs,
) -> str:
    """使用已配置提供商、兼容 LightRAG 的 LLM 函数。"""
    provider = get_llm_provider()

    messages: list[LLMMessage] = []

    if system_prompt:
        messages.append(LLMMessage(role="system", content=system_prompt))

    if history_messages:
        for msg in history_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            messages.append(LLMMessage(role=role, content=content))

    messages.append(LLMMessage(role="user", content=prompt))

    return await provider.acomplete(
        messages, temperature=0.0, max_tokens=4096,
    )


async def _kg_embed(texts: list[str]) -> np.ndarray:
    """使用已配置提供商、兼容 LightRAG 的向量化函数。"""
    provider = get_embedding_provider()
    return await provider.embed(texts)


# ---------------------------------------------------------------------------
# 主服务
# ---------------------------------------------------------------------------

class KnowledgeGraphService:
    """
    由 LightRAG 支撑的按工作区知识图谱服务。

    存储：基于文件（图使用 NetworkX，向量使用 NanoVectorDB）。
    每个知识库拥有独立的工作目录。
    """

    def __init__(
        self,
        workspace_id: int,
        kg_language: str | None = None,
        kg_entity_types: list[str] | None = None,
    ):
        self.workspace_id = workspace_id
        self.working_dir = str(
            settings.BASE_DIR / "data" / "lightrag" / f"kb_{workspace_id}"
        )
        # 按工作区覆盖（回退到全局设置）
        self.kg_language = kg_language or settings.MYRAG_KG_LANGUAGE
        self.kg_entity_types = kg_entity_types or settings.MYRAG_KG_ENTITY_TYPES
        self._rag = None
        self._initialized = False

    async def _get_rag(self):
        """延迟初始化 LightRAG 实例。"""
        if self._rag is not None and self._initialized:
            return self._rag

        from lightrag import LightRAG
        from lightrag.utils import wrap_embedding_func_with_attrs
        from lightrag.kg.shared_storage import initialize_pipeline_status

        os.makedirs(self.working_dir, exist_ok=True)

        # 从已配置提供商获取动态向量维度
        emb_provider = get_embedding_provider()
        embedding_dim = emb_provider.get_dimension()

        # 检测切换提供商时的维度不匹配
        dim_marker = Path(self.working_dir) / ".embedding_dim"
        if dim_marker.exists():
            prev_dim = int(dim_marker.read_text().strip())
            if prev_dim != embedding_dim:
                logger.warning(
                    f"Embedding dimension changed ({prev_dim} → {embedding_dim}) "
                    f"for workspace {self.workspace_id}. Clearing KG data for rebuild."
                )
                shutil.rmtree(self.working_dir)
                os.makedirs(self.working_dir, exist_ok=True)
        dim_marker.write_text(str(embedding_dim))

        @wrap_embedding_func_with_attrs(embedding_dim=embedding_dim, max_token_size=8192)
        async def embedding_func(texts: list[str]) -> np.ndarray:
            return await _kg_embed(texts)

        self._rag = LightRAG(
            working_dir=self.working_dir,
            llm_model_func=_kg_llm_complete,
            embedding_func=embedding_func,
            chunk_token_size=settings.MYRAG_KG_CHUNK_TOKEN_SIZE,
            enable_llm_cache=True,
            kv_storage="JsonKVStorage",
            vector_storage="NanoVectorDBStorage",
            graph_storage="NetworkXStorage",
            doc_status_storage="JsonDocStatusStorage",
            addon_params={
                "language": self.kg_language,
                "entity_types": self.kg_entity_types,
            },
        )

        await self._rag.initialize_storages()
        await initialize_pipeline_status()
        self._initialized = True

        logger.info(
            f"LightRAG initialized for workspace {self.workspace_id} "
            f"(embedding_dim={embedding_dim})"
        )
        return self._rag

    def _document_key(self, document_id: int) -> str:
        """LightRAG 里的稳定文档 ID。文件内容变了，身份证号也别跟着变。"""
        return f"doc-myrag-{self.workspace_id}-{document_id}"

    async def _delete_document_ids(self, rag, document_ids: set[str]) -> None:
        """删得掉就删；本来不存在也不算世界末日。"""
        for doc_id in document_ids:
            result = await rag.adelete_by_doc_id(doc_id)
            if getattr(result, "status", "success") not in {"success", "not_found"}:
                logger.warning(
                    f"KG deletion returned {getattr(result, 'status', 'unknown')} "
                    f"for {doc_id}: {getattr(result, 'message', '')}"
                )

    async def ingest(
        self,
        markdown_content: str,
        document_id: int | None = None,
        previous_content: str | None = None,
    ) -> None:
        """
        将 Markdown 内容写入知识图谱。
        LightRAG 会自动提取实体和关系。
        """
        rag = await self._get_rag()

        if not markdown_content.strip():
            logger.warning(f"Empty content for workspace {self.workspace_id}, skipping KG ingest")
            return

        try:
            if document_id is None:
                await rag.ainsert(markdown_content)
            else:
                ids_to_delete = {self._document_key(document_id)}

                # 兼容升级前的数据：以前没传稳定 ID，LightRAG 用正文 MD5 当 ID。
                # 把旧 ID 也算出来删掉，免得历史图谱阴魂不散。
                if previous_content:
                    from lightrag.utils import compute_mdhash_id
                    ids_to_delete.add(
                        compute_mdhash_id(previous_content, prefix="doc-")
                    )

                await self._delete_document_ids(rag, ids_to_delete)
                await rag.ainsert(
                    markdown_content,
                    ids=self._document_key(document_id),
                )
            logger.info(
                f"KG ingested {len(markdown_content)} chars for workspace {self.workspace_id}"
            )

            # 检查是否真的提取到了实体
            try:
                all_nodes = await rag.chunk_entity_relation_graph.get_all_nodes()
                if not all_nodes:
                    from app.core.config import settings
                    model = (
                        settings.OLLAMA_MODEL
                        if settings.LLM_PROVIDER.lower() == "ollama"
                        else settings.LLM_MODEL_FAST
                    )
                    logger.warning(
                        f"KG extraction produced 0 entities for workspace {self.workspace_id}. "
                        f"Model '{model}' may not support LightRAG's entity extraction format. "
                        f"Consider using a larger model (e.g. qwen3:14b, gemma3:12b) for KG."
                    )
            except Exception:
                pass

        except Exception as e:
            logger.error(f"KG ingest failed for workspace {self.workspace_id}: {e}")
            raise

    async def delete_document(
        self,
        document_id: int,
        previous_content: str | None = None,
    ) -> None:
        """只删除一篇文档贡献的图谱数据，别为了拔根草把整块地翻了。"""
        rag = await self._get_rag()
        ids_to_delete = {self._document_key(document_id)}

        if previous_content:
            from lightrag.utils import compute_mdhash_id
            ids_to_delete.add(compute_mdhash_id(previous_content, prefix="doc-"))

        await self._delete_document_ids(rag, ids_to_delete)

    async def query(
        self,
        question: str,
        mode: str = "hybrid",
        top_k: int = 10,
    ) -> str:
        """
        查询知识图谱。

        参数：
            question: 自然语言问题
            mode: 查询模式 —— "naive"、"local"、"global"、"hybrid"
            top_k: 结果数量

        返回：
            带知识图谱增强答案的 LightRAG 响应文本
        """
        from lightrag import QueryParam

        rag = await self._get_rag()

        try:
            result = await asyncio.wait_for(
                rag.aquery(
                    question,
                    param=QueryParam(mode=mode, top_k=top_k),
                ),
                timeout=settings.MYRAG_KG_QUERY_TIMEOUT,
            )
            return result or ""
        except asyncio.TimeoutError:
            logger.warning(
                f"KG query timed out after {settings.MYRAG_KG_QUERY_TIMEOUT}s "
                f"for workspace {self.workspace_id}"
            )
            return ""
        except Exception as e:
            logger.error(f"KG query failed for workspace {self.workspace_id}: {e}")
            return ""

    async def cleanup(self) -> None:
        """在关闭时完成存储收尾。"""
        if self._rag:
            try:
                await self._rag.finalize_storages()
                logger.info(f"KG storages finalized for workspace {self.workspace_id}")
            except Exception as e:
                logger.warning(f"KG cleanup failed for workspace {self.workspace_id}: {e}")
            self._rag = None
            self._initialized = False

    def delete_project_data(self) -> None:
        """删除该知识库的全部知识图谱数据。"""
        path = Path(self.working_dir)
        if path.exists():
            shutil.rmtree(path)
            logger.info(f"Deleted KG data for workspace {self.workspace_id}")
        self._rag = None
        self._initialized = False

    # ------------------------------------------------------------------
    # 知识图谱探索（第 9 阶段）
    # ------------------------------------------------------------------

    async def get_entities(
        self,
        search: str | None = None,
        entity_type: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        """
        列出知识图谱中的全部实体。

        返回包含以下字段的字典列表：name、entity_type、description、degree。
        """
        rag = await self._get_rag()
        storage = rag.chunk_entity_relation_graph

        try:
            all_nodes = await storage.get_all_nodes()
        except Exception as e:
            logger.error(f"Failed to get KG nodes for workspace {self.workspace_id}: {e}")
            return []

        entities = []
        for node in all_nodes:
            node_id = node.get("id", "")
            etype = node.get("entity_type", "Unknown")
            desc = node.get("description", "")

            # 过滤
            if entity_type and etype.lower() != entity_type.lower():
                continue
            if search and search.lower() not in node_id.lower():
                continue

            # 获取度（关系数量）
            try:
                degree = await storage.node_degree(node_id)
            except Exception:
                degree = 0

            entities.append({
                "name": node_id,
                "entity_type": etype,
                "description": desc,
                "degree": degree,
            })

        # 按度降序排序
        entities.sort(key=lambda e: e["degree"], reverse=True)

        return entities[offset:offset + limit]

    async def get_relationships(
        self,
        entity_name: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        """
        列出知识图谱中的关系。

        如果提供了 entity_name，则只返回与该实体相关的关系。
        返回包含以下字段的字典列表：source、target、description、keywords、weight。
        """
        rag = await self._get_rag()
        storage = rag.chunk_entity_relation_graph

        try:
            all_edges = await storage.get_all_edges()
        except Exception as e:
            logger.error(f"Failed to get KG edges for workspace {self.workspace_id}: {e}")
            return []

        relationships = []
        for edge in all_edges:
            src = edge.get("source", "")
            tgt = edge.get("target", "")

            if entity_name:
                if entity_name.lower() not in (src.lower(), tgt.lower()):
                    continue

            relationships.append({
                "source": src,
                "target": tgt,
                "description": edge.get("description", ""),
                "keywords": edge.get("keywords", ""),
                "weight": float(edge.get("weight", 1.0)),
            })

        return relationships[:limit]

    async def get_graph_data(
        self,
        center_entity: str | None = None,
        max_depth: int = 3,
        max_nodes: int = 150,
    ) -> dict:
        """
        导出供前端可视化的图谱数据。

        返回 {nodes: [...], edges: [...], is_truncated: bool}。
        """
        rag = await self._get_rag()
        storage = rag.chunk_entity_relation_graph

        try:
            label = center_entity if center_entity else "*"
            kg = await storage.get_knowledge_graph(
                node_label=label,
                max_depth=max_depth,
                max_nodes=max_nodes,
            )
        except Exception as e:
            logger.error(f"Failed to get KG graph for workspace {self.workspace_id}: {e}")
            return {"nodes": [], "edges": [], "is_truncated": False}

        nodes = []
        for n in kg.nodes:
            props = n.properties if hasattr(n, "properties") else {}
            try:
                degree = await storage.node_degree(n.id)
            except Exception:
                degree = 0
            nodes.append({
                "id": n.id,
                "label": n.id,
                "entity_type": props.get("entity_type", "Unknown"),
                "degree": degree,
            })

        edges = []
        for e in kg.edges:
            props = e.properties if hasattr(e, "properties") else {}
            edges.append({
                "source": e.source,
                "target": e.target,
                "label": props.get("description", "")[:80],
                "weight": float(props.get("weight", 1.0)),
            })

        return {
            "nodes": nodes,
            "edges": edges,
            "is_truncated": kg.is_truncated if hasattr(kg, "is_truncated") else False,
        }

    async def get_relevant_context(
        self,
        question: str,
        max_entities: int = 20,
        max_relationships: int = 30,
    ) -> str:
        """
        从原始知识图谱数据构建 RAG 上下文（不经过 LLM 生成）。

        与调用 LightRAG 的 aquery()（会用 LLM 生成叙述，且可能产生幻觉）不同，
        此方法：
          1. 将问题分词为关键词
          2. 查找名称匹配任一关键词的实体
          3. 获取连接这些实体的关系
          4. 将所有内容格式化为结构化的事实文本

        返回：
            实体 + 关系的结构化字符串；未找到内容时返回 ""。
        """
        rag = await self._get_rag()
        storage = rag.chunk_entity_relation_graph

        try:
            all_nodes = await storage.get_all_nodes()
            all_edges = await storage.get_all_edges()
        except Exception as e:
            logger.error(f"Failed to get raw KG data for workspace {self.workspace_id}: {e}")
            return ""

        if not all_nodes:
            return ""

        # -- 1. 从问题中提取关键词 --
        # 简单但有效：拆分、转小写、过滤短词
        raw_tokens = question.lower().split()
        # 同时处理带连字符 / 版本号的词，例如 "deepseek-v3.2"
        keywords = set()
        for token in raw_tokens:
            # 移除边缘的标点
            cleaned = token.strip(".,?!:;\"'()[]{}").lower()
            if len(cleaned) >= 2:
                keywords.add(cleaned)

        if not keywords:
            return ""

        # -- 2. 查找匹配的实体 --
        matched_entity_names: set[str] = set()
        entity_info: dict[str, dict] = {}  # 名称 → {类型, 描述}

        for node in all_nodes:
            node_id = node.get("id", "")
            node_lower = node_id.lower()

            # 检查任一关键词是否为实体名称的子串，或反之
            matched = False
            for kw in keywords:
                if kw in node_lower or node_lower in kw:
                    matched = True
                    break
                # 同时检查多词关键词（例如 "deepseek" 匹配 "DEEPSEEK-V3.2"）
                for part in node_lower.split("-"):
                    if kw in part or part in kw:
                        matched = True
                        break
                if matched:
                    break

            if matched:
                matched_entity_names.add(node_id)
                entity_info[node_id] = {
                    "entity_type": node.get("entity_type", "Unknown"),
                    "description": node.get("description", ""),
                }

        if not matched_entity_names and len(all_nodes) <= 50:
            # 小图：默认包含前几个实体
            for node in all_nodes[:10]:
                nid = node.get("id", "")
                matched_entity_names.add(nid)
                entity_info[nid] = {
                    "entity_type": node.get("entity_type", "Unknown"),
                    "description": node.get("description", ""),
                }

        if not matched_entity_names:
            return ""

        # 限制实体数量
        matched_list = list(matched_entity_names)[:max_entities]

        # -- 3. 查找与匹配实体相关的关系 --
        relevant_rels: list[dict] = []
        matched_lower = {n.lower() for n in matched_list}

        for edge in all_edges:
            src = edge.get("source", "")
            tgt = edge.get("target", "")
            if src.lower() in matched_lower or tgt.lower() in matched_lower:
                relevant_rels.append({
                    "source": src,
                    "target": tgt,
                    "description": edge.get("description", ""),
                    "keywords": edge.get("keywords", ""),
                })
                # 同时补充可能遗漏的关联实体
                if src not in entity_info:
                    # 查找节点信息
                    for n in all_nodes:
                        if n.get("id", "") == src:
                            entity_info[src] = {
                                "entity_type": n.get("entity_type", "Unknown"),
                                "description": n.get("description", ""),
                            }
                            break
                if tgt not in entity_info:
                    for n in all_nodes:
                        if n.get("id", "") == tgt:
                            entity_info[tgt] = {
                                "entity_type": n.get("entity_type", "Unknown"),
                                "description": n.get("description", ""),
                            }
                            break

            if len(relevant_rels) >= max_relationships:
                break

        # -- 4. 格式化为结构化文本 --
        parts: list[str] = []

        # 实体部分
        if matched_list:
            parts.append("Entities found in documents:")
            for name in matched_list:
                info = entity_info.get(name, {})
                etype = info.get("entity_type", "")
                desc = info.get("description", "")
                # 截断过长的描述
                if len(desc) > 200:
                    desc = desc[:200] + "..."
                type_str = f" [{etype}]" if etype and etype != "Unknown" else ""
                if desc:
                    parts.append(f"- {name}{type_str}: {desc}")
                else:
                    parts.append(f"- {name}{type_str}")

        # 关系部分
        if relevant_rels:
            parts.append("")
            parts.append("Relationships:")
            for rel in relevant_rels:
                desc = rel["description"]
                if len(desc) > 150:
                    desc = desc[:150] + "..."
                if desc:
                    parts.append(f"- {rel['source']} → {rel['target']}: {desc}")
                else:
                    parts.append(f"- {rel['source']} → {rel['target']}")

        result = "\n".join(parts)
        logger.info(
            f"KG raw context: {len(matched_list)} entities, "
            f"{len(relevant_rels)} relationships for workspace {self.workspace_id}"
        )
        return result

    async def get_analytics(self) -> dict:
        """
        计算知识图谱分析摘要。

        返回：entity_count、relationship_count、entity_types、top_entities、avg_degree。
        """
        rag = await self._get_rag()
        storage = rag.chunk_entity_relation_graph

        try:
            all_nodes = await storage.get_all_nodes()
            all_edges = await storage.get_all_edges()
        except Exception as e:
            logger.error(f"Failed to get KG analytics for workspace {self.workspace_id}: {e}")
            return {
                "entity_count": 0,
                "relationship_count": 0,
                "entity_types": {},
                "top_entities": [],
                "avg_degree": 0.0,
            }

        entity_count = len(all_nodes)
        relationship_count = len(all_edges)

        # 统计实体类型
        type_counts: dict[str, int] = {}
        entities_with_degree = []
        for node in all_nodes:
            etype = node.get("entity_type", "Unknown")
            type_counts[etype] = type_counts.get(etype, 0) + 1
            try:
                degree = await storage.node_degree(node.get("id", ""))
            except Exception:
                degree = 0
            entities_with_degree.append({
                "name": node.get("id", ""),
                "entity_type": etype,
                "description": node.get("description", ""),
                "degree": degree,
            })

        # 按度排序以得到头部实体
        entities_with_degree.sort(key=lambda e: e["degree"], reverse=True)
        top_entities = entities_with_degree[:10]

        avg_degree = (
            sum(e["degree"] for e in entities_with_degree) / entity_count
            if entity_count > 0
            else 0.0
        )

        return {
            "entity_count": entity_count,
            "relationship_count": relationship_count,
            "entity_types": type_counts,
            "top_entities": top_entities,
            "avg_degree": round(avg_degree, 2),
        }
