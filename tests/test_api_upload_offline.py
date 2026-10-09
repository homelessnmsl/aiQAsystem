"""POST /api/upload 离线测试（stub 入库步骤，不依赖真实解析/嵌入）"""
import pytest
from fastapi.testclient import TestClient

import app.main as app_main
from app.core.errors import CODE_PARSE_FAILED, BizError
from app.services.ingestion import IngestResult
from app.services.repository import Repository


@pytest.fixture()
def client():
    return TestClient(app_main.app, raise_server_exceptions=False)


@pytest.fixture()
def temp_env(tmp_path, monkeypatch):
    """独立 SQLite 台账 + 独立上传目录"""
    repo = Repository(path=tmp_path / "app.db")
    monkeypatch.setattr("app.api.upload.get_repository", lambda: repo)
    monkeypatch.setattr(app_main.settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    return repo


def _stub_ingest(monkeypatch, behavior=None):
    """替换 ingest_file：记录调用并按 behavior 返回/抛错"""
    calls = []

    def fake_ingest(path, *, doc_id=None, store=None, provider=None):
        calls.append({"path": str(path), "doc_id": doc_id})
        if behavior is not None:
            outcome = behavior(path)
            if isinstance(outcome, Exception):
                raise outcome
            if outcome is not None:
                return outcome
        return IngestResult(
            doc_id=doc_id, filename=path.name, file_type=path.suffix.lstrip("."),
            chunk_count=5, elapsed_ms=12, created_at="2026-10-08T10:00:00+08:00",
        )

    monkeypatch.setattr("app.api.upload.ingest_file", fake_ingest)
    return calls


def test_upload_success(client, temp_env, monkeypatch):
    calls = _stub_ingest(monkeypatch)
    resp = client.post("/api/upload", files=[("files", ("01_员工手册.txt", b"hello world", "text/plain"))])
    body = resp.json()
    assert resp.status_code == 200 and body["code"] == 0
    assert body["message"] == "上传完成：成功 1 个"

    data = body["data"]
    assert (data["total"], data["succeeded"], data["failed"]) == (1, 1, 0)
    item = data["items"][0]
    assert item["doc_id"].startswith("doc_")
    assert item["filename"] == "01_员工手册.txt"
    assert item["file_type"] == "txt"
    assert item["size_bytes"] == 11
    assert item["status"] == "success" and item["chunk_count"] == 5
    assert item["error_code"] is None and item["error_message"] is None

    # 文件已落盘：data/uploads/{doc_id}/原始文件名（架构 7.1）
    saved = app_main.settings.upload_dir / item["doc_id"] / "01_员工手册.txt"
    assert saved.exists() and saved.read_bytes() == b"hello world"
    assert calls[0]["doc_id"] == item["doc_id"]

    # 台账已置 success
    row = temp_env.get_document(item["doc_id"])
    assert row["status"] == "success" and row["chunk_count"] == 5


def test_upload_partial_failure(client, temp_env, monkeypatch):
    def behavior(path):
        if path.name == "broken.pdf":
            return BizError(CODE_PARSE_FAILED, "《broken.pdf》解析失败：文件可能已损坏或为扫描件")
        return None

    _stub_ingest(monkeypatch, behavior)
    resp = client.post("/api/upload", files=[
        ("files", ("good.pdf", b"%PDF-1.4 ok", "application/pdf")),
        ("files", ("broken.pdf", b"broken", "application/pdf")),
    ])
    body = resp.json()
    assert resp.status_code == 200 and body["code"] == 0
    assert body["message"] == "上传完成：成功 1 个，失败 1 个"
    assert body["data"]["succeeded"] == 1 and body["data"]["failed"] == 1

    failed_item = body["data"]["items"][1]
    assert failed_item["doc_id"] is None and failed_item["status"] == "failed"
    assert failed_item["error_code"] == 2002
    assert "解析失败" in failed_item["error_message"]


def test_upload_all_failed(client, temp_env, monkeypatch):
    _stub_ingest(monkeypatch, lambda path: BizError(CODE_PARSE_FAILED, f"《{path.name}》解析失败"))
    resp = client.post("/api/upload", files=[
        ("files", ("a.pdf", b"x", "application/pdf")),
        ("files", ("b.pdf", b"y", "application/pdf")),
    ])
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == 2002
    assert len(body["data"]["items"]) == 2
    assert all(item["status"] == "failed" for item in body["data"]["items"])


def test_upload_without_files(client, temp_env):
    resp = client.post("/api/upload", files=[])
    assert resp.status_code == 413
    assert resp.json()["code"] == 1003


def test_upload_too_many_files(client, temp_env, monkeypatch):
    monkeypatch.setattr(app_main.settings, "MAX_FILES_PER_UPLOAD", 5)
    files = [("files", (f"f{i}.txt", b"x", "text/plain")) for i in range(6)]
    resp = client.post("/api/upload", files=files)
    assert resp.status_code == 413
    assert resp.json()["code"] == 1003
    assert "最多上传 5 个" in resp.json()["message"]


def test_upload_bad_extension(client, temp_env):
    resp = client.post("/api/upload", files=[("files", ("virus.exe", b"MZ", "application/octet-stream"))])
    assert resp.status_code == 415
    assert resp.json()["code"] == 1002
    assert "不支持的文件类型" in resp.json()["message"]


def test_upload_oversize(client, temp_env, monkeypatch):
    monkeypatch.setattr(app_main.settings, "MAX_FILE_SIZE_MB", 1)
    big = b"a" * (1024 * 1024 + 1)
    resp = client.post("/api/upload", files=[("files", ("big.txt", big, "text/plain"))])
    assert resp.status_code == 413
    assert resp.json()["code"] == 1003
    assert "超过 1MB" in resp.json()["message"]
