"""GET /api/documents 离线测试（独立 SQLite 台账）"""
import pytest
from fastapi.testclient import TestClient

import app.main as app_main
from app.services.repository import Repository


@pytest.fixture()
def client():
    return TestClient(app_main.app, raise_server_exceptions=False)


@pytest.fixture()
def temp_repo(tmp_path, monkeypatch):
    repo = Repository(path=tmp_path / "app.db")
    monkeypatch.setattr("app.api.documents.get_repository", lambda: repo)
    return repo


def _seed(repo: Repository):
    repo.upsert_document(doc_id="doc_1", filename="01_员工手册.pdf", file_type="pdf", size_bytes=196254,
                         upload_time="2026-10-08T10:00:00+08:00", chunk_count=6, status="success")
    repo.upsert_document(doc_id="doc_2", filename="03_报销制度与费用标准.xlsx", file_type="xlsx", size_bytes=8012,
                         upload_time="2026-10-08T11:00:00+08:00", chunk_count=4, status="success")
    repo.upsert_document(doc_id="doc_3", filename="broken.pdf", file_type="pdf", size_bytes=1024,
                         upload_time="2026-10-08T12:00:00+08:00", status="failed")


def test_list_documents(client, temp_repo):
    _seed(temp_repo)
    body = client.get("/api/documents").json()
    assert body["code"] == 0
    data = body["data"]
    assert data["total"] == 2 and data["page"] == 1 and data["page_size"] == 20
    assert [item["doc_id"] for item in data["items"]] == ["doc_2", "doc_1"]
    first = data["items"][0]
    for key in ("doc_id", "filename", "file_type", "size_bytes", "chunk_count", "upload_time", "status"):
        assert key in first
    assert first["filename"] == "03_报销制度与费用标准.xlsx"


def test_list_documents_filters(client, temp_repo):
    _seed(temp_repo)
    assert client.get("/api/documents", params={"file_type": "pdf"}).json()["data"]["total"] == 1
    assert client.get("/api/documents", params={"keyword": "报销"}).json()["data"]["total"] == 1
    assert client.get("/api/documents", params={"status": "failed"}).json()["data"]["total"] == 1
    assert client.get("/api/documents", params={"status": "all"}).json()["data"]["total"] == 3
    assert client.get("/api/documents", params={"page": 2, "page_size": 1}).json()["data"]["items"][0]["doc_id"] == "doc_1"


def test_list_documents_invalid_params(client, temp_repo):
    resp = client.get("/api/documents", params={"file_type": "exe"})
    assert resp.status_code == 400 and resp.json()["code"] == 1001
    resp = client.get("/api/documents", params={"status": "unknown"})
    assert resp.status_code == 400 and resp.json()["code"] == 1001
    resp = client.get("/api/documents", params={"page_size": 0})
    assert resp.status_code == 400 and resp.json()["code"] == 1001
    assert resp.json()["data"]["errors"][0]["field"] == "page_size"


# ============ W3-06：删除文档（接口文档 2.5） ============
class _FakeVectorStore:
    """替身：记录 delete_by_doc 调用，可注入错误"""

    def __init__(self, result: int = 6, error: Exception | None = None):
        self.result = result
        self.error = error
        self.deleted: list[str] = []

    def delete_by_doc(self, doc_id: str) -> int:
        if self.error is not None:
            raise self.error
        self.deleted.append(doc_id)
        return self.result


def test_delete_document_ok(client, temp_repo, monkeypatch, tmp_path):
    _seed(temp_repo)
    fake_store = _FakeVectorStore(result=6)
    monkeypatch.setattr("app.api.documents.vector_store", fake_store)
    monkeypatch.setattr(app_main.settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    doc_dir = tmp_path / "uploads" / "doc_1"
    doc_dir.mkdir(parents=True)
    (doc_dir / "01_员工手册.pdf").write_bytes(b"%PDF")

    resp = client.delete("/api/documents/doc_1")
    body = resp.json()
    assert resp.status_code == 200 and body["code"] == 0
    assert body["data"] == {"doc_id": "doc_1", "deleted_chunks": 6}
    assert fake_store.deleted == ["doc_1"]
    assert temp_repo.get_document("doc_1")["status"] == "deleted"
    assert not doc_dir.exists()  # 原始文件目录已删除

    # 默认列表不含已删除；status=all 可见且状态正确
    assert client.get("/api/documents").json()["data"]["total"] == 1
    all_items = client.get("/api/documents", params={"status": "all"}).json()["data"]["items"]
    assert any(item["doc_id"] == "doc_1" and item["status"] == "deleted" for item in all_items)


def test_delete_document_not_found(client, temp_repo):
    _seed(temp_repo)
    resp = client.delete("/api/documents/doc_missing")
    assert resp.status_code == 404 and resp.json()["code"] == 1005
    assert resp.json()["message"] == "文档不存在或已被删除"


def test_delete_document_twice(client, temp_repo, monkeypatch, tmp_path):
    """重复删除：第二次返回 1005（已删除），其它文档不受影响"""
    _seed(temp_repo)
    monkeypatch.setattr("app.api.documents.vector_store", _FakeVectorStore(result=6))
    monkeypatch.setattr(app_main.settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    assert client.delete("/api/documents/doc_1").json()["code"] == 0
    second = client.delete("/api/documents/doc_1")
    assert second.status_code == 404 and second.json()["code"] == 1005
    assert temp_repo.get_document("doc_2")["status"] == "success"


def test_delete_document_vector_error(client, temp_repo, monkeypatch):
    """向量库删除失败 → 2003（HTTP 503）；台账保持 success 可重试（架构 6.11）"""
    from app.core.errors import CODE_VECTOR_STORE_ERROR, BizError

    _seed(temp_repo)
    fake_store = _FakeVectorStore(error=BizError(CODE_VECTOR_STORE_ERROR, "知识库暂时不可用，请稍后重试"))
    monkeypatch.setattr("app.api.documents.vector_store", fake_store)
    resp = client.delete("/api/documents/doc_1")
    assert resp.status_code == 503 and resp.json()["code"] == 2003
    assert temp_repo.get_document("doc_1")["status"] == "success"
