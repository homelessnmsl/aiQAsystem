"""扩容语料生成器（W3-04 Rerank 复核用；AD）

生成 40+ 份虚构企业文档，与 tests/sample_docs 的 10 份基线文档共同构成 ≥50 份知识库，
用于验证"知识库扩容 + 新旧版本干扰"后 Rerank 是否值得开启。

用法（仓库根目录执行）：
    python scripts/generate_corpus.py --target data/corpus_w3          # 生成（覆盖同名文件）
    python scripts/generate_corpus.py --target data/corpus_w3 --clean  # 先清空目录再生成

约束：
- 全部为虚构企业与人物，不含真实涉密信息（NFR-S-03）；
- 涉及评测集已有事实（年假天数/报销标准/试用期等）时只做交叉引用，不重复定义数字；
- 覆盖 md / txt / docx / xlsx 四种格式，并有意包含「旧版制度」等干扰项。
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import List, Tuple

COMPANY = "星海智联科技有限公司"


def _md(title: str, sections: List[Tuple[str, str]]) -> str:
    """把 (小节标题, 正文) 列表渲染为 Markdown 文档"""
    lines = [f"# {title}", ""]
    for heading, body in sections:
        lines.append(f"## {heading}")
        lines.append("")
        lines.append(body.strip())
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 语料模板
# --------------------------------------------------------------------------- #
def department_handbooks() -> List[Tuple[str, str, str]]:
    """各部门工作手册（7 份 md）"""
    departments = [
        ("研发中心", "产品研发、技术架构与运维保障", "代码评审双人复核、每周五发布窗口、线上变更需值班同学在场"),
        ("产品部", "产品规划、需求分析与竞品跟踪", "需求进入研发前须有验收标准；每季度做一次竞品拆解"),
        ("客户成功部", "客户支持、实施交付与客户培训", "一线工单 2 小时响应；实施交付按里程碑验收"),
        ("市场部", "品牌推广、市场活动与渠道合作", "对外发布物料需品牌规范审核；活动复盘 3 日内归档"),
        ("人力资源部", "招聘、培训、绩效与员工关系", "招聘面试不少于两轮；绩效校准会每半年一次"),
        ("财务部", "核算、报销、预算与税务", "预算超支 10% 需部门负责人书面说明"),
        ("行政部", "办公环境、资产管理与后勤支持", "办公用品申领每周二、四集中处理"),
    ]
    docs = []
    for name, duty, rules in departments:
        content = _md(
            f"{name}工作手册（2026 版）",
            [
                ("一、部门职责", f"{COMPANY}{name}负责{duty}。"),
                ("二、协作界面", f"与人力资源部、财务部、行政部的对接事项按公司流程执行；跨部门需求走 OA 工单。"),
                ("三、工作规则", f"本部门工作规则：{rules}。"),
                ("四、常见问题", "内部流程细节可咨询部门助理；制度类问题以《员工手册》为准。"),
            ],
        )
        docs.append((f"E{len(docs) + 1:02d}_{name}工作手册.md", "md", content))
    return docs


def management_policies() -> List[Tuple[str, str, str]]:
    """管理制度类（12 份，md/txt）"""
    topics = [
        ("项目管理制度", "项目立项、里程碑与复盘", "立项需明确目标、范围与验收标准；里程碑延期超过一周需上报 PMO"),
        ("采购管理办法", "采购申请、比价与验收", "单笔 5 万元以上采购需三家比价；验收合格后方可付款"),
        ("设备与资产管理规范", "办公设备领用、维修与报废", "设备领用登记到人；报废需行政部与财务部双签"),
        ("信息安全管理制度", "账号、终端与数据安全", "账号不得共用；敏感数据外发需审批；离职当天回收权限"),
        ("数据分级与使用规范", "数据分级、脱敏与外发", "数据分为公开/内部/敏感三级；敏感级外发需脱敏并记录"),
        ("知识产权管理办法", "专利、软著与商标管理", "职务发明归公司所有；申报材料由法务统一提交"),
        ("保密制度", "商业秘密范围与保密义务", "保密信息包括客户名单、源代码与未公开财务数据"),
        ("加班与调休管理规定", "加班申请与调休使用", "加班需事前申请；调休应在三个月内使用完毕"),
        ("培训与发展管理办法", "内训、外训与学习积分", "外训需签订服务期协议；内训讲师计学习积分"),
        ("绩效管理办法", "目标设定、评估与校准", "考核周期为上下半年各一次；结果与调薪池挂钩"),
        ("招聘与面试流程", "需求发布、面试与录用", "面试结论 3 个工作日内反馈；offer 审批走线上流程"),
        ("内部沟通规范", "会议、邮件与即时通讯", "会议须有议程与纪要；工作日 12:00-13:00 为午休时间"),
    ]
    docs = []
    for index, (title, topic, rule) in enumerate(topics, start=1):
        content = _md(
            f"{title}（2026 版）",
            [
                ("一、目的", f"为规范{topic}，结合公司实际制定本办法。"),
                ("二、适用范围", f"本办法适用于{COMPANY}全体员工。"),
                ("三、主要内容", f"{rule}。"),
                ("四、解释与修订", "本办法由归口管理部门负责解释，自发布之日起施行。"),
            ],
        )
        suffix = "md" if index % 3 else "txt"
        docs.append((f"E{len(docs) + 8:02d}_{title}.{suffix}", suffix, content))
    return docs


def product_docs() -> List[Tuple[str, str, str]]:
    """产品资料（6 份 md）"""
    products = [
        ("星海智答·智能客服平台功能清单", "会话接入、意图识别、坐席辅助与质检", "支持网页、微信与电话渠道路由"),
        ("星海知识库·企业知识管理系统白皮书", "文档接入、语义检索与引用溯源", "支持 PDF/Word/Excel/TXT/Markdown 与来源引用"),
        ("星海工单·客户服务工单系统使用手册", "工单创建、流转与升级", "工单超时自动升级至值班主管"),
        ("智能客服平台 API 接入指南", "鉴权、会话接口与回调", "接口调用需使用 HTTPS 与 Bearer 鉴权"),
        ("星海智答 V3.3 版本说明", "意图识别与质检能力升级", "新增多轮追问与知识库命中分析看板"),
        ("星海智答 V3.4 版本说明", "知识溯源与检索优化", "新增引用溯源展示与检索结果对比工具"),
    ]
    docs = []
    for index, (title, topic, detail) in enumerate(products, start=1):
        content = _md(
            title,
            [
                ("一、产品概述", f"本文档介绍{topic}相关内容。"),
                ("二、核心能力", f"{detail}。"),
                ("三、部署与运维", "支持私有化与混合云部署；升级前需完成回归测试。"),
                ("四、服务支持", "使用问题可通过客户成功部工单获取支持。"),
            ],
        )
        docs.append((f"E{len(docs) + 20:02d}_{title}.md", "md", content))
    return docs


def customer_docs() -> List[Tuple[str, str, str]]:
    """客户与交付类（4 份，含 docx）"""
    docs = [
        ("客户案例集（制造业与金融业）", "实施周期平均 6~8 周；客户满意度回访在验收后 30 天内完成"),
        ("实施交付手册", "交付分启动、配置、联调、验收四个阶段；每阶段输出交付物清单"),
        ("客户成功 SOP", "续约前 90 天启动健康度评估；红黄牌客户需双周跟进"),
        ("服务等级协议（SLA）模板", "系统可用性不低于 99.5%；重大故障 30 分钟内响应"),
    ]
    result = []
    for index, (title, detail) in enumerate(docs, start=1):
        content = _md(title, [("一、说明", detail), ("二、流程", "具体流程以合同与项目计划为准。")])
        result.append((f"E{len(result) + 26:02d}_{title}.docx", "docx", content))
    return result


def operation_docs() -> List[Tuple[str, str, str]]:
    """运营台账类（6 份，含 xlsx）"""
    docs = [
        ("供应商名录", "供应商名称\t类别\t合作年限\t联系人\n杭州云帆科技\t软件外包\t3\t王经理\n上海衡信咨询\t管理咨询\t2\t李经理\n深圳蓝湾印制\t印务服务\t5\t陈经理"),
        ("固定资产台账", "资产编号\t名称\t使用人\t状态\nZC-001\t笔记本电脑\t研发中心\t在用\nZC-002\t显示器\t产品部\t在用\nZC-003\t投影仪\t行政部\t维修中"),
        ("办公用品申领清单", "物品\t规格\t库存\t申领频次\nA4 打印纸\t70g\t120 包\t每周\n签字笔\t0.5mm\t300 支\t每月\n笔记本\tA5\t150 本\t每季"),
        ("会议室使用规范", "会议室需提前一天预订；超时使用需顺延至空闲时段；会后请关闭设备"),
        ("团建与活动安排", "部门团建每半年一次；活动预算按人均标准执行，需行政部备案"),
        ("值班与应急联络表", "工作日晚间与节假日按值班表轮值；重大故障先电话通知值班主管"),
    ]
    result = []
    for index, (title, detail) in enumerate(docs, start=1):
        if "\t" in detail:
            header, *rows = detail.split("\n")
            columns = header.split("\t")
            lines = ["# " + title, "", "| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
            for row in rows:
                lines.append("| " + " | ".join(row.split("\t")) + " |")
            content, suffix = "\n".join(lines), "md"
        else:
            content, suffix = _md(title, [("一、说明", detail)]), "txt"
        if index in (1, 2, 3):
            suffix = "xlsx"
        result.append((f"E{len(result) + 30:02d}_{title}.{suffix}", suffix, content))
    return result


def training_docs() -> List[Tuple[str, str, str]]:
    """培训与合规（3 份 md）"""
    docs = [
        ("新员工 30 天成长指南", "第一周熟悉环境与制度；第二周进入项目；第四周提交学习总结"),
        ("内训课程表（2026 上半年）", "课程覆盖产品知识、客户沟通与信息安全；每门课程计 2 学习积分"),
        ("合规培训材料（反商业贿赂）", "禁止收受供应商礼品；业务招待需按标准执行并留存记录"),
    ]
    result = []
    for index, (title, detail) in enumerate(docs, start=1):
        content = _md(title, [("一、要点", detail), ("二、要求", "完成学习后需通过在线测验。")])
        result.append((f"E{len(result) + 36:02d}_{title}.md", "md", content))
    return result


def distractors() -> List[Tuple[str, str, str]]:
    """干扰项：旧版制度与相似主题（4 份，md/txt）"""
    docs = [
        (
            "E40_考勤管理规定（2024 旧版）.txt",
            "txt",
            "考勤管理规定（2024 旧版）\n"
            "1. 工作时间\n公司上班时间为 9:30-18:30，午休 12:00-13:00。\n"
            "2. 年假\n年假标准按当年度公司通知执行（本旧版不再维护，以《员工手册》为准）。\n"
            "3. 产假\n女职工产假为 128 天（本旧版条款已废止，现行标准见《考勤与假期管理规定》）。\n"
            "4. 说明\n本文件为 2024 年存档版本，仅用于历史查询。\n",
        ),
        (
            "E41_报销标准说明（2024 旧版）.txt",
            "txt",
            "报销标准说明（2024 旧版）\n"
            "1. 差旅住宿\n一线城市住宿上限 400 元/晚（已调整，现行标准见《报销制度与费用标准》）。\n"
            "2. 市内交通\n市内交通实报实销，单次上限 80 元。\n"
            "3. 说明\n本文件为历史存档，如与现行制度冲突以现行制度为准。\n",
        ),
        (
            "E42_竞品对比分析（内部参考）.md",
            "md",
            "# 竞品对比分析（内部参考）\n\n## 一、对比维度\n功能覆盖、检索准确率、引用溯源、部署方式与价格。\n\n## 二、结论\n同类产品在引用溯源与知识库管理上差异较大，需结合客户场景评估。\n",
        ),
        (
            "E43_行业观察摘录.md",
            "md",
            "# 行业观察摘录\n\n## 一、趋势\n企业知识管理正从文档中心转向问答式入口，检索质量与可追溯性成为关键指标。\n\n## 二、启示\n建设知识库需同步治理文档版本，避免新旧制度并存造成答案冲突。\n",
        ),
    ]
    return docs


# --------------------------------------------------------------------------- #
# 写盘
# --------------------------------------------------------------------------- #
def write_docx(path: Path, content: str) -> None:
    """用 python-docx 写 Word 文档（按行解析 # / ## 标题）"""
    from docx import Document

    document = Document()
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("## "):
            document.add_heading(line[3:], level=2)
        elif line.startswith("# "):
            document.add_heading(line[2:], level=1)
        else:
            document.add_paragraph(line)
    document.save(str(path))


def write_xlsx(path: Path, content: str) -> None:
    """把 Markdown 表格转成 Excel 工作表"""
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "明细"
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if all(set(cell) <= {"-", ":", " "} for cell in cells if cell):
                continue
            sheet.append(cells)
    workbook.save(str(path))


def main() -> int:
    """命令行入口：生成全部扩展文档并打印摘要"""
    parser = argparse.ArgumentParser(description="生成 W3-04 扩容语料（虚构企业文档）")
    parser.add_argument("--target", default="data/corpus_w3", help="输出目录")
    parser.add_argument("--clean", action="store_true", help="生成前清空目录")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    target = Path(args.target)
    if not target.is_absolute():
        target = root / target
    if args.clean and target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    all_docs = (
        department_handbooks()
        + management_policies()
        + product_docs()
        + customer_docs()
        + operation_docs()
        + training_docs()
        + distractors()
    )
    written = 0
    for filename, suffix, content in all_docs:
        path = target / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        if suffix == "docx":
            write_docx(path, content)
        elif suffix == "xlsx":
            write_xlsx(path, content)
        else:
            path.write_text(content, encoding="utf-8")
        written += 1

    counts: dict = {}
    for path in target.rglob("*"):
        if path.is_file():
            counts[path.suffix] = counts.get(path.suffix, 0) + 1
    print(f"[完成] 生成 {written} 份文档 → {target}")
    print(f"[格式] " + ", ".join(f"{ext or '无后缀'}: {num}" for ext, num in sorted(counts.items())))
    print(f"[提示] 与 tests/sample_docs 的 10 份合并后共 {written + 10} 份，满足 ≥50 份要求")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
