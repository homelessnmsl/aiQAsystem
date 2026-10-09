"""下载本地模型（Embedding / Rerank；默认从 ModelScope 魔搭；W2-03 / W3）

背景：部分网络无法直连 huggingface.co（sentence-transformers 自动下载会失败）。
本脚本用纯 HTTP 从 ModelScope 拉取模型文件到本地目录，之后把 .env 的
EMBEDDING_MODEL / RERANK_MODEL 指向该目录即可（sentence-transformers 原生支持本地目录）。

用法（仓库根目录执行）：
    python scripts/download_model.py                                  # 默认下载 Embedding 模型
    python scripts/download_model.py --repo BAAI/bge-reranker-base --target C:/models/bge-reranker-base
    python scripts/download_model.py --repo BAAI/bge-reranker-base    # 重新运行会自动跳过已下好的文件

注：文件清单自动从 ModelScope API 获取（自动跳过 onnx/ 与重复权重）；已存在且大小一致的文件会跳过；
单个文件失败不会中断整体（结尾汇总失败清单，重跑即可补齐）。
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List

import requests

#: API 不可用时的内置兜底清单（Embedding 模型 bge-small-zh-v1.5）
FILES = [
    "modules.json",
    "config.json",
    "config_sentence_transformers.json",
    "sentence_bert_config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "vocab.txt",
    "1_Pooling/config.json",
]

REPO_FILE_URL = "https://www.modelscope.cn/api/v1/models/{repo}/repo"
REPO_FILES_API = "https://www.modelscope.cn/api/v1/models/{repo}/repo/files"
DEFAULT_TARGET = Path.home() / ".cache" / "aiqasystem" / "models" / "bge-small-zh-v1.5"

#: 与模型无关的说明/索引文件（跳过）
SKIP_FILES = {".gitattributes", "README.md", "configuration.json"}


def discover_files(repo: str) -> List[Dict[str, object]]:
    """列出仓库文件 [{path, size}]；自动跳过目录条目 / onnx / 重复权重"""
    try:
        response = requests.get(
            REPO_FILES_API.format(repo=repo),
            params={"Revision": "master", "Recursive": "true"},
            timeout=30,
        )
        response.raise_for_status()
        entries = response.json().get("Data", {}).get("Files", [])
    except Exception:
        return [{"path": name, "size": 0} for name in FILES]

    paths = [entry.get("Path") for entry in entries if entry.get("Path")]
    has_safetensors = "model.safetensors" in paths

    listed: List[Dict[str, object]] = []
    for entry in entries:
        path = entry.get("Path") or ""
        name = Path(path).name
        if not path or path in SKIP_FILES or path.startswith("onnx/"):
            continue
        if "." not in name:                      # 目录条目（如 onnx）
            continue
        if path == "pytorch_model.bin" and has_safetensors:  # 权重已有 safetensors 版本
            continue
        listed.append({"path": path, "size": int(entry.get("Size") or 0)})

    return sorted(listed, key=lambda item: str(item["path"])) or [
        {"path": name, "size": 0} for name in FILES
    ]


def download_file(repo: str, file_path: str, target: Path, expected_size: int = 0) -> int:
    """下载单个模型文件；已存在且大小一致 → 跳过；返回本次下载字节数"""
    if target.exists() and expected_size and target.stat().st_size == expected_size:
        print(f"[跳过] {file_path}（已存在 {expected_size / 1024 / 1024:.1f} MB）")
        return 0

    response = requests.get(
        REPO_FILE_URL.format(repo=repo),
        params={"Revision": "master", "FilePath": file_path},
        stream=True,
        timeout=180,
    )
    response.raise_for_status()
    target.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with target.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=256 * 1024):
            if chunk:
                handle.write(chunk)
                size += len(chunk)
    return size


def main() -> int:
    """命令行入口：列出清单 → 逐文件下载（失败不中断）→ 打印 .env 配置提示"""
    parser = argparse.ArgumentParser(description="从 ModelScope 下载模型到本地目录")
    parser.add_argument("--repo", default="BAAI/bge-small-zh-v1.5", help="ModelScope 仓库 ID")
    parser.add_argument("--target", default=str(DEFAULT_TARGET), help="本地保存目录")
    args = parser.parse_args()

    target = Path(args.target)
    files = discover_files(args.repo)
    print(f"[下载] {args.repo} → {target}")
    print(f"[清单] {len(files)} 个文件（已跳过 onnx/重复权重/说明文件）")

    total = 0
    failed: List[str] = []
    for entry in files:
        path = str(entry["path"])
        try:
            size = download_file(args.repo, path, target / path, int(entry.get("size") or 0))
        except Exception as exc:  # 单文件失败不中断（下次重跑补齐）
            failed.append(path)
            print(f"[失败] {path}: {exc}")
            continue
        total += size
        if size:
            print(f"[完成] {path}（{size / 1024 / 1024:.1f} MB）")

    print(f"\n本次新增 {total / 1024 / 1024:.1f} MB；失败 {len(failed)} 个")
    if failed:
        print("失败文件：", ", ".join(failed), "（重新运行本脚本即可补齐）")
        return 1
    print(f"请在 .env 中配置：EMBEDDING_MODEL 或 RERANK_MODEL = {target.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
