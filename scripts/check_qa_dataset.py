# -*- coding: utf-8 -*-
"""校验 QA 评测集的完整性与分布（PE 任务 W1-16 配套工具）。

用法：
    py -3 scripts/check_qa_dataset.py
    py -3 scripts/check_qa_dataset.py tests/qa_dataset_v1.json
    py -3 scripts/check_qa_dataset.py --sample-dir tests/sample_docs

检查项：
1. JSON 可解析且为数组；条数 = 20；id 唯一且形如 QA-001；
2. 必填字段齐全：id / question / expected_answer / type / difficulty / tags / answer_type / key_points；
3. answered 题必须有 expected_source 与 expected_location；not_found 题两者必须为 null；
4. expected_source 指向的示例文档必须存在（目录存在时校验，可用 --sample-dir 指定）；
5. 难度分布 8 / 9 / 3；无答案兜底不少于 4 条；五类题型齐全；
6. 多轮追问题必须提供 follow_up_questions。

退出码：0 = 通过（允许有警告）；1 = 存在问题。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "tests" / "qa_dataset_v1.json"
DEFAULT_SAMPLE_DIR = ROOT / "tests" / "sample_docs"

REQUIRED_FIELDS = ("id", "question", "expected_answer", "type", "difficulty", "tags", "answer_type", "key_points")
VALID_DIFFICULTY = {"easy", "medium", "hard"}
VALID_ANSWER_TYPE = {"answered", "not_found", "clarify"}
EXPECTED_DIFFICULTY = {"easy": 8, "medium": 9, "hard": 3}
REQUIRED_TYPES = {"制度查询", "流程查询", "表格取数", "多轮追问", "无答案兜底"}
MIN_NOT_FOUND = 4
EXPECTED_TOTAL = 20


def parse_args(argv: list[str]) -> argparse.Namespace:
    """解析命令行参数（评测集路径与示例文档目录）。"""
    parser = argparse.ArgumentParser(description="校验 QA 评测集（tests/qa_dataset_v1.json）")
    parser.add_argument("dataset", nargs="?", default=str(DEFAULT_DATASET), help="评测集 JSON 路径")
    parser.add_argument("--sample-dir", default=str(DEFAULT_SAMPLE_DIR), help="示例文档目录，用于校验 expected_source 是否存在")
    return parser.parse_args(argv)


def check(dataset_path: Path, sample_dir: Path) -> int:
    """执行全部检查，返回退出码（0 通过 / 1 有问题）。"""
    errors: list[str] = []
    warnings: list[str] = []

    if not dataset_path.exists():
        print(f"[错误] 找不到评测集文件：{dataset_path}")
        return 1
    try:
        data = json.loads(dataset_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[错误] JSON 解析失败：{exc}")
        return 1
    if not isinstance(data, list):
        print("[错误] 评测集根节点必须是 JSON 数组（与需求文档 7.3 一致）")
        return 1
    if len(data) != EXPECTED_TOTAL:
        errors.append(f"总条数应为 {EXPECTED_TOTAL} 条，实际 {len(data)} 条")

    seen_ids: set[str] = set()
    difficulty_counter: Counter = Counter()
    type_counter: Counter = Counter()
    not_found = 0
    sources: set[str] = set()

    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            errors.append(f"第 {index} 条：不是 JSON 对象")
            continue
        item_id = item.get("id") if isinstance(item.get("id"), str) else f"(缺少 id，序号 {index})"

        for field in REQUIRED_FIELDS:
            value = item.get(field)
            if value is None or (isinstance(value, (str, list)) and len(value) == 0):
                errors.append(f"{item_id}：缺少必填字段 {field}")

        if item_id in seen_ids:
            errors.append(f"{item_id}：id 重复")
        seen_ids.add(item_id)
        if not (item_id.startswith("QA-") and item_id[3:].isdigit()):
            errors.append(f"{item_id}：id 命名应形如 QA-001")

        answer_type = item.get("answer_type")
        if answer_type not in VALID_ANSWER_TYPE:
            errors.append(f"{item_id}：answer_type 非法（{answer_type}）")
        difficulty = item.get("difficulty")
        if difficulty not in VALID_DIFFICULTY:
            errors.append(f"{item_id}：difficulty 非法（{difficulty}），应为 easy / medium / hard")
        else:
            difficulty_counter[difficulty] += 1
        item_type = item.get("type")
        if item_type not in REQUIRED_TYPES:
            errors.append(f"{item_id}：type 非法（{item_type}）")
        else:
            type_counter[item_type] += 1

        if answer_type == "not_found":
            not_found += 1
            if item.get("expected_source") is not None or item.get("expected_location") is not None:
                errors.append(f"{item_id}：not_found 题的 expected_source / expected_location 必须为 null")
        else:
            source = item.get("expected_source")
            location = item.get("expected_location")
            if not source or not location:
                errors.append(f"{item_id}：可答题必须给出 expected_source 与 expected_location")
            else:
                sources.add(source)

        if not isinstance(item.get("tags"), list) or not item.get("tags"):
            errors.append(f"{item_id}：tags 必须为非空数组")
        if not isinstance(item.get("key_points"), list) or not item.get("key_points"):
            errors.append(f"{item_id}：key_points 必须为非空数组（M-03 部分给分用）")
        if item_type == "多轮追问":
            follow = item.get("follow_up_questions")
            if not isinstance(follow, list) or not follow:
                errors.append(f"{item_id}：多轮追问题必须提供 follow_up_questions 数组")

    for level, expected in EXPECTED_DIFFICULTY.items():
        actual = difficulty_counter.get(level, 0)
        if actual != expected:
            errors.append(f"难度分布：{level} 应为 {expected} 条，实际 {actual} 条")
    if not_found < MIN_NOT_FOUND:
        errors.append(f"无答案兜底题应不少于 {MIN_NOT_FOUND} 条（M-04），实际 {not_found} 条")
    for item_type in REQUIRED_TYPES:
        if type_counter.get(item_type, 0) == 0:
            errors.append(f"题型覆盖：缺少「{item_type}」类题目")

    if sample_dir.exists():
        existing = {path.name for path in sample_dir.iterdir() if path.is_file()}
        for source in sorted(sources):
            if source not in existing:
                errors.append(f"expected_source 指向的文件不存在：{source}")
    else:
        warnings.append(f"示例文档目录不存在，跳过来源文件校验：{sample_dir}")

    print(f"评测集：{dataset_path}")
    print(
        "总条数：{}｜难度：easy {} / medium {} / hard {}｜无答案兜底：{}".format(
            len(data),
            difficulty_counter.get("easy", 0),
            difficulty_counter.get("medium", 0),
            difficulty_counter.get("hard", 0),
            not_found,
        )
    )
    print("题型：" + "、".join(f"{name} {count}" for name, count in sorted(type_counter.items())))
    if sources:
        print("来源文档：" + "、".join(sorted(sources)))
    for message in warnings:
        print(f"[警告] {message}")
    for message in errors:
        print(f"[错误] {message}")
    if errors:
        print(f"结果：未通过（{len(errors)} 处问题）")
        return 1
    print("结果：全部通过")
    return 0


def main(argv: list[str] | None = None) -> int:
    """脚本入口：解析参数并执行校验。"""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    return check(Path(args.dataset).resolve(), Path(args.sample_dir).resolve())


if __name__ == "__main__":
    raise SystemExit(main())