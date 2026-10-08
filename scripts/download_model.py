"""下载本地 Embedding 模型（默认从 ModelScope 魔搭；W2-03）

背景：部分网络无法直连 huggingface.co（sentence-transformers 自动下载会失败）。
本脚本用纯 HTTP 从 ModelScope 拉取模型文件到本地目录，之后把 .env 的
EMBEDDING_MODEL 指向该目录即可（sentence-transformers 原生支持本地目录）。

用法（仓库根目录执行）：
    python scripts/download_model.py
    python scripts/download_model.py --repo BAAI/bge-small-zh-v1.5 --target D:/models/bge-small-zh

下载完成后在 .env 中设置（Windows 路径用正斜杠）：
    EMBEDDING_MODEL=C:/Users/HP/.cache/aiqasystem/models/bge-small-zh-v1.5
"""
from __future__ import annotations

import argparse
from pathlib import Path

import requests

#: sentence-transformers 加载模型所需文件（model.safetensors 已含权重，无需 pytorch_model.bin）
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

REPO_URL = "https://www.modelscope.cn/api/v1/models/{repo}/repo"
DEFAULT_TARGET = Path.home() / ".cache" / "aiqasystem" / "models" / "bge-small-zh-v1.5"


def download_file(repo: str, file_path: str, target: Path) -> int:
    """下载单个模型文件（重复运行覆盖），返回字节数"""
    response = requests.get(
        REPO_URL.format(repo=repo),
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
    """命令行入口：逐个下载模型文件并打印结果"""
    parser = argparse.ArgumentParser(description="从 ModelScope 下载 Embedding 模型到本地目录")
    parser.add_argument("--repo", default="BAAI/bge-small-zh-v1.5", help="ModelScope 仓库 ID")
    parser.add_argument("--target", default=str(DEFAULT_TARGET), help="本地保存目录")
    args = parser.parse_args()

    target = Path(args.target)
    print(f"[下载] {args.repo} → {target}")
    total = 0
    for name in FILES:
        try:
            size = download_file(args.repo, name, target / name)
        except Exception as exc:  # 网络/仓库异常
            print(f"[失败] {name}: {exc}")
            return 1
        total += size
        print(f"[完成] {name}（{size / 1024 / 1024:.1f} MB）")

    print(f"\n合计 {total / 1024 / 1024:.1f} MB")
    print(f"请在 .env 中配置：EMBEDDING_MODEL={target.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
