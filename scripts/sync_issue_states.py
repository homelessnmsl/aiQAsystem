# -*- coding: utf-8 -*-
"""Gitee Issue 状态同步脚本（PM 工具）

按 issues_batch.json 的 status 字段同步 Gitee Issue 状态：
- status 以 ✅ 开头 → 置为已完成（state=closed）
- 其他（⚠️/🔄/⬜）→ 保持打开，不动
幂等：已完成的不会重复操作。

用法（仓库根目录）：
  python scripts/sync_issue_states.py --dry-run
  python scripts/sync_issue_states.py --token <私人令牌>
  $env:GITEE_TOKEN="..."; python scripts/sync_issue_states.py
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
API = "https://gitee.com/api/v5"


def load_token(args) -> str:
    token = args.token or None
    if not token:
        import os
        token = os.environ.get("GITEE_TOKEN", "")
    if not token:
        f = ROOT / ".gitee_token"
        if f.exists():
            token = f.read_text(encoding="utf-8").strip()
    return token


def fetch_issues(owner: str, repo: str, token: str) -> dict[str, tuple[str, str]]:
    """返回 {title: (number, state)}，state 为 open/closed。"""
    result: dict[str, tuple[str, str]] = {}
    for page in range(1, 6):
        resp = requests.get(
            f"{API}/repos/{owner}/{repo}/issues",
            params={"state": "all", "per_page": 100, "page": page, "access_token": token},
            timeout=30,
        )
        if resp.status_code == 401:
            raise PermissionError("令牌无效或未授权（401）")
        if resp.status_code != 200:
            raise RuntimeError(f"拉取 Issue 失败：HTTP {resp.status_code} {resp.text[:200]}")
        batch = resp.json()
        for it in batch:
            if isinstance(it, dict) and it.get("title"):
                result[it["title"]] = (it["number"], it.get("state", ""))
        if len(batch) < 100:
            break
        time.sleep(0.4)
    return result


def set_closed(owner: str, repo: str, token: str, number: str) -> None:
    resp = requests.patch(
        f"{API}/repos/{owner}/issues/{number}",
        data={"access_token": token, "repo": repo, "state": "closed"},
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"关闭 #{number} 失败：HTTP {resp.status_code} {resp.text[:200]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="按看板状态同步 Gitee Issue 状态")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要关闭的条目")
    parser.add_argument("--token", help="Gitee 私人令牌（也可用 GITEE_TOKEN 或 .gitee_token）")
    args = parser.parse_args()

    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    owner, repo, issues = data["owner"], data["repo"], data["issues"]
    token = load_token(args)

    to_close = [it for it in issues if str(it.get("status", "")).startswith("✅")]
    print(f"待关闭（✅）{len(to_close)} 条 / 保持打开 {len(issues) - len(to_close)} 条")

    if args.dry_run:
        for i, it in enumerate(to_close, 1):
            print(f"  {i:02d}. 将置为已完成：{it['title']}")
        return 0

    if not token:
        print("错误：未提供令牌（--token / GITEE_TOKEN / .gitee_token）", file=sys.stderr)
        return 1

    try:
        remote = fetch_issues(owner, repo, token)
    except (PermissionError, RuntimeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    done, missing, failed = 0, 0, 0
    for i, it in enumerate(to_close, 1):
        title = it["title"]
        info = remote.get(title)
        if info is None:
            print(f"  {i:02d}. MISSING（远端未找到） {title}")
            missing += 1
            continue
        number, state = info
        if state == "closed":
            print(f"  {i:02d}. SKIP（已是已完成） {title}")
            continue
        try:
            set_closed(owner, repo, token, number)
            print(f"  {i:02d}. CLOSED #{number} {title}")
            done += 1
            time.sleep(0.5)
        except RuntimeError as exc:
            print(f"  {i:02d}. ERROR #{number} {title}（{exc}）", file=sys.stderr)
            failed += 1

    print(f"汇总：已关闭 {done} / 远端未找到 {missing} / 失败 {failed}")
    return 3 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
