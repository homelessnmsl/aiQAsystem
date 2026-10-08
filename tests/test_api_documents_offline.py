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
