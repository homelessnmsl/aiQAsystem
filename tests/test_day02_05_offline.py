"""day02~day05 课程代码离线冒烟测试（不调用真实 DeepSeek API）

校验各天应用可导入、基础路由返回统一结构；day01 见 test_day01_offline.py。
运行（仓库根目录）：
    python -m pytest tests/test_day02_05_offline.py
"""
import pytest
from fastapi.testclient import TestClient

import day02.main as day02_main
import day03.main as day03_main
import day04.main as day04_main
import day05.main as day05_main

DAY_APPS = [
    ("day02-多轮对话", day02_main.app, "/api/health"),
    ("day03-工具调用", day03_main.app, "/api/health"),
    ("day04-流式输出", day04_main.app, "/api/health"),
    ("day05-整合版", day05_main.app, "/health"),
]


@pytest.mark.parametrize("name,app,health_path", DAY_APPS, ids=[item[0] for item in DAY_APPS])
def test_root_and_health(name, app, health_path):
    client = TestClient(app)
    root = client.get("/").json()
    assert root["code"] == 0
    assert "message" in root and "data" in root

    health = client.get(health_path).json()
    assert health["code"] == 0
