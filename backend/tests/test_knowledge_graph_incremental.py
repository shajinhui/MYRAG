from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from app.services.knowledge_graph_service import KnowledgeGraphService


class KnowledgeGraphIncrementalTests(IsolatedAsyncioTestCase):
    async def test_replacing_document_reuses_stable_id(self):
        fake_rag = SimpleNamespace(
            adelete_by_doc_id=AsyncMock(
                return_value=SimpleNamespace(status="not_found", message="")
            ),
            ainsert=AsyncMock(),
            chunk_entity_relation_graph=SimpleNamespace(
                get_all_nodes=AsyncMock(return_value=[{"id": "ok"}])
            ),
        )

        service = KnowledgeGraphService.__new__(KnowledgeGraphService)
        service.workspace_id = 3
        service._get_rag = AsyncMock(return_value=fake_rag)

        await service.ingest(
            "新版内容",
            document_id=8,
            previous_content="旧版内容",
        )

        fake_rag.ainsert.assert_awaited_once_with(
            "新版内容",
            ids="doc-myrag-3-8",
        )
        deleted_ids = {
            call.args[0]
            for call in fake_rag.adelete_by_doc_id.await_args_list
        }
        self.assertIn("doc-myrag-3-8", deleted_ids)
        self.assertEqual(len(deleted_ids), 2)
