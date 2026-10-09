"""Repository（SQLite 台账）单元测试（架构 7.2；W2-05/06/07）"""
from app.services.repository import Repository


def _repo(tmp_path) -> Repository:
    return Repository(path=tmp_path / "app.db")


def test_documents_upsert_and_list(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert_document(doc_id="doc_1", filename="a.pdf", file_type="pdf", size_bytes=100,
                         upload_time="2026-10-08T10:00:00+08:00", chunk_count=3, status="success")
    repo.upsert_document(doc_id="doc_2", filename="b.txt", file_type="txt", size_bytes=50,
                         upload_time="2026-10-08T11:00:00+08:00", chunk_count=2, status="success")
    repo.upsert_document(doc_id="doc_3", filename="broken.pdf", file_type="pdf", size_bytes=10,
                         upload_time="2026-10-08T12:00:00+08:00", status="failed")

    total, items = repo.list_documents(status="success")
    assert total == 2
    assert [item["doc_id"] for item in items] == ["doc_2", "doc_1"]  # 按 upload_time 倒序

    total_failed, failed_items = repo.list_documents(status="failed")
    assert total_failed == 1 and failed_items[0]["status"] == "failed"

    total_all, _ = repo.list_documents(status="all")
    assert total_all == 3

    total_kw, keyword_items = repo.list_documents(keyword="a.p")
    assert total_kw == 1 and keyword_items[0]["filename"] == "a.pdf"

    total_type, _ = repo.list_documents(file_type="txt", status="all")
    assert total_type == 1

    _, page2 = repo.list_documents(page=2, page_size=1, status="success")
    assert page2[0]["doc_id"] == "doc_1"


def test_documents_stats_and_delete(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert_document(doc_id="doc_1", filename="a.pdf", file_type="pdf", size_bytes=1,
                         upload_time="t", chunk_count=3, status="success")
    repo.upsert_document(doc_id="doc_2", filename="b.pdf", file_type="pdf", size_bytes=1,
                         upload_time="t", chunk_count=4, status="success")
    assert repo.count_documents() == 2
    assert repo.sum_chunks() == 7

    # upsert 更新（幂等覆盖）
    repo.upsert_document(doc_id="doc_1", filename="a.pdf", file_type="pdf", size_bytes=1,
                         upload_time="t", chunk_count=9, status="success")
    assert repo.sum_chunks() == 13

    repo.delete_document_row("doc_1")
    assert repo.get_document("doc_1") is None
    assert repo.get_document("doc_2")["chunk_count"] == 4

    assert repo.delete_all_documents() == 1
    assert repo.get_document("doc_2") is None
    total_all, _ = repo.list_documents(status="all")
    assert total_all == 0


def test_conversation_and_messages(tmp_path):
    repo = _repo(tmp_path)
    repo.ensure_conversation("conv_1", title="年假")
    repo.ensure_conversation("conv_1")  # 幂等：不覆盖已有标题
    repo.add_message(message_id="msg_1", session_id="conv_1", role="user",
                     content="年假多少天？", trace_id="tr_x", created_at="2026-10-08T10:00:00+08:00")
    repo.add_message(message_id="msg_2", session_id="conv_1", role="assistant",
                     content="5 天 [1]", citations="[]", trace_id="tr_x", latency_ms=123,
                     created_at="2026-10-08T10:00:01+08:00")

    messages = repo.list_messages("conv_1")
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["latency_ms"] == 123
    assert messages[1]["citations"] == "[]"
