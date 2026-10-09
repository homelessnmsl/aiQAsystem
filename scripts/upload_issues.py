# -*- coding: utf-8 -*-
"""Gitee Issue 批量补传脚本（PM 工具 · W2-15）

数据源：scripts/issues_batch.json（由 docs/第1周任务清单.md 与 docs/第2周任务清单.md 生成）
行为：按标题判重，已存在的 Issue 跳过（幂等，可重复执行）。

用法（仓库根目录）：
  # 预演：只打印将创建什么，不请求写接口
  python scripts/upload_issues.py --dry-run

  # 真实上传（令牌三种来源：--token 参数 / GITEE_TOKEN 环境变量 / 仓库根 .gitee_token 文件）
  python scripts/upload_issues.py
  python scripts/upload_issues.py --token 你的私人令牌
  $env:GITEE_TOKEN="你的私人令牌"; python scripts/upload_issues.py

令牌获取：Gitee → 设置 → 私人令牌 → 生成新令牌，勾选 issues 权限。
安全：令牌只读入内存，日志不打印；.gitee_token 已被 .gitignore 忽略。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "scripts" / "issues_batch.json"
TOKEN_FILE = ROOT / ".gitee_token"
API = "https://gitee.com/api/v5"


def mask(token: str) -> str:
    return (token[:6] + "****") if token else "<未提供>"


def load_token(args) -> str:
    token = args.token or None
    if not token:
        import os
        token = os.environ.get("GITEE_TOKEN", "")
    if not token and TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    return token


def load_issues() -> list[dict]:
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    owner = data["owner"]
    repo = data["repo"]
    issues = data["issues"]
    print(f"数据文件：{DATA_FILE.name}（{data['total']} 条，owner={owner} repo={repo}）")
    return owner, repo, issues


def existing_titles(owner: str, repo: str, token: str) -> set[str]:
    """拉取仓库全部 Issue 标题用于判重（分页最多 5 页）。"""
    titles: set[str] = set()
    for page in range(1, 6):
        resp = requests.get(
            f"{API}/repos/{owner}/{repo}/issues",
            params={"state": "all", "per_page": 100, "page": page, "access_token": token},
            timeout=30,
        )
        if resp.status_code == 401:
            raise PermissionError("令牌无效或未授权（401），请检查私人令牌与 issues 权限")
        if resp.status_code != 200:
            raise RuntimeError(f"拉取已有 Issue 失败：HTTP {resp.status_code} {resp.text[:200]}")
        batch = resp.json()
        titles.update(item.get("title", "") for item in batch if isinstance(item, dict))
        if len(batch) < 100:
            break
        time.sleep(0.4)
    return titles


def create_issue(owner: str, repo: str, token: str, issue: dict) -> str:
    resp = requests.post(
        f"{API}/repos/{owner}/{repo}/issues",
        data={
            "access_token": token,
            "repo": repo,
            "title": issue["title"],
            "body": issue["body"],
            "issue_type": "task",
        },
        timeout=60,
    )
    if resp.status_code in (200, 201):
        body = resp.json()
        return f"#{body.get('number')} {body.get('html_url', '')}".strip()
    if resp.status_code == 401:
        raise PermissionError("令牌无效或未授权（401）")
    raise RuntimeError(f"创建失败 HTTP {resp.status_code}：{resp.text[:200]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Gitee Issue 批量补传（幂等）")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要创建的内容，不请求接口")
    parser.add_argument("--token", help="Gitee 私人令牌（也可用 GITEE_TOKEN 环境变量或 .gitee_token 文件）")
    parser.add_argument("--limit", type=int, default=0, help="最多创建 N 条（调试用，0 表示全部）")
    args = parser.parse_args()

    owner, repo, issues = load_issues()
    todo = issues[: args.limit] if args.limit > 0 else issues
    token = load_token(args)

    if args.dry_run:
        print(f"[DRY-RUN] 令牌：{mask(token)}（不会真实上传）")
        for i, it in enumerate(todo, 1):
            print(f"  {i:02d}. 将创建：{it['title']}")
        print(f"[DRY-RUN] 共 {len(todo)} 条（判重检查在真实运行时执行）")
        return 0

    if not token:
        print("错误：未提供令牌。用法：--token <令牌> 或 GITEE_TOKEN 环境变量或仓库根 .gitee_token 文件", file=sys.stderr)
        return 1

    print(f"令牌：{mask(token)}")
    try:
        exists = existing_titles(owner, repo, token)
    except (PermissionError, RuntimeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    print(f"仓库已有 Issue {len(exists)} 条，开始上传…")

    created, skipped, failed = 0, 0, 0
    for i, it in enumerate(todo, 1):
        if it["title"] in exists:
            print(f"  {i:02d}. SKIP（已存在） {it['title']}")
            skipped += 1
            continue
        try:
            url = create_issue(owner, repo, token, it)
            print(f"  {i:02d}. CREATE {url} {it['title']}")
            created += 1
            time.sleep(0.6)
        except PermissionError as exc:
            print(f"  {i:02d}. AUTH_FAIL {it['title']}（{exc}）", file=sys.stderr)
            return 2
        except RuntimeError as exc:
            print(f"  {i:02d}. ERROR {it['title']}（{exc}）", file=sys.stderr)
            failed += 1
            time.sleep(1.0)

    print(f"完成：新建 {created} / 跳过 {skipped} / 失败 {failed}")
    return 3 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
