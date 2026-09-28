# -*- coding: utf-8 -*-
"""生成企业知识库智能问答系统的示例数据集（虚构企业：星海智联科技有限公司）。

用途：RA 任务 W1-08 交付物，为文档解析、检索、引用溯源、评测提供多格式测试数据。
运行：python tests/sample_docs/generate_sample_docs.py
依赖：python-docx、openpyxl、reportlab（仅生成时需要，仓库已提交生成结果，使用者无需运行）

数据设计原则：
1. 全部内容为虚构，不涉及任何真实企业信息；
2. 关键事实（年假天数、住宿标准、SLA 时限等）全库唯一，避免自相矛盾；
3. 含干扰项（D-08 考勤规定 / D-09 供应商对账），用于检验检索区分度与拒答能力。
"""

import os

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from docx.oxml.ns import qn
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib import colors

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
COMPANY = "星海智联科技有限公司"

# ---------------------------------------------------------------- 中文字体注册

def register_cn_fonts():
    """注册中文字体，保证 PDF 文本可被提取、且不依赖阅读器内置字体。"""
    candidates = [
        (r"C:\Windows\Fonts\msyh.ttc", 0, "CN", "CN-Bold"),
        (r"C:\Windows\Fonts\simhei.ttf", 0, "CN", "CN-Bold"),
    ]
    for path, idx, regular, bold in candidates:
        if not os.path.exists(path):
            continue
        try:
            pdfmetrics.registerFont(TTFont(regular, path, subfontIndex=idx))
            bold_path = r"C:\Windows\Fonts\msyhbd.ttc"
            if os.path.exists(bold_path):
                pdfmetrics.registerFont(TTFont(bold, bold_path, subfontIndex=0))
            else:
                pdfmetrics.registerFont(TTFont(bold, path, subfontIndex=idx))
            return True
        except Exception as exc:  # pragma: no cover
            print("字体注册失败：%s (%s)" % (path, exc))
    raise RuntimeError("未找到可用的中文字体，请安装微软雅黑或黑体")


# ---------------------------------------------------------------- PDF 通用工具

def _styles():
    return {
        "title": ParagraphStyle("title", fontName="CN-Bold", fontSize=18, leading=28, alignment=TA_CENTER, spaceAfter=6),
        "subtitle": ParagraphStyle("subtitle", fontName="CN", fontSize=10.5, leading=16, alignment=TA_CENTER, textColor=colors.grey, spaceAfter=14),
        "h1": ParagraphStyle("h1", fontName="CN-Bold", fontSize=14, leading=22, spaceBefore=10, spaceAfter=6),
        "h2": ParagraphStyle("h2", fontName="CN-Bold", fontSize=11.5, leading=18, spaceBefore=6, spaceAfter=4),
        "body": ParagraphStyle("body", fontName="CN", fontSize=10.5, leading=17, firstLineIndent=0, spaceAfter=3),
    }


def _page_number(canvas, doc):
    canvas.saveState()
    canvas.setFont("CN", 9)
    canvas.setFillColor(colors.grey)
    canvas.drawCentredString(A4[0] / 2.0, 15 * mm, "第 %d 页" % doc.page)
    canvas.restoreState()


def build_pdf(filename, doc_title, subtitle, chapters):
    """chapters: [(章标题, [段落文本, ...]), ...]，每章另起一页，便于按页码引用。"""
    st = _styles()
    path = os.path.join(OUT_DIR, filename)
    doc = SimpleDocTemplate(path, pagesize=A4, topMargin=22 * mm, bottomMargin=20 * mm,
                            leftMargin=20 * mm, rightMargin=20 * mm, title=doc_title)
    story = [Paragraph(doc_title, st["title"]), Paragraph(subtitle, st["subtitle"])]
    for index, (chapter_title, paragraphs) in enumerate(chapters):
        if index > 0:
            story.append(PageBreak())
        story.append(Paragraph(chapter_title, st["h1"]))
        for text in paragraphs:
            style = st["h2"] if text.startswith("§") else st["body"]
            story.append(Paragraph(text.lstrip("§"), style))
        story.append(Spacer(1, 4))
    doc.build(story, onFirstPage=_page_number, onLaterPages=_page_number)
    return path


def build_docx(filename, doc_title, subtitle, blocks):
    """blocks: [("h1"/"h2"/"p"/"li", 文本) 或 ("table", [表头], [[行...], ...])]"""
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "微软雅黑"
    normal.font.size = Pt(10.5)
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")

    head = doc.add_paragraph()
    head.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = head.add_run(doc_title)
    run.bold = True
    run.font.size = Pt(18)
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub_run = sub.add_run(subtitle)
    sub_run.font.size = Pt(10)
    sub_run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)

    for block in blocks:
        kind = block[0]
        if kind == "h1":
            doc.add_heading(block[1], level=1)
        elif kind == "h2":
            doc.add_heading(block[1], level=2)
        elif kind == "p":
            doc.add_paragraph(block[1])
        elif kind == "li":
            doc.add_paragraph(block[1], style="List Number")
        elif kind == "table":
            header, rows = block[1], block[2]
            table = doc.add_table(rows=1, cols=len(header))
            table.style = "Light Grid Accent 1"
            for i, text in enumerate(header):
                cell = table.rows[0].cells[i]
                cell.text = str(text)
                for paragraph in cell.paragraphs:
                    for r in paragraph.runs:
                        r.bold = True
            for row in rows:
                cells = table.add_row().cells
                for i, text in enumerate(row):
                    cells[i].text = str(text)
    path = os.path.join(OUT_DIR, filename)
    doc.save(path)
    return path


def build_xlsx(filename, sheets):
    """sheets: [(表名, [表头], [[行...], ...]), ...]"""
    wb = Workbook()
    wb.remove(wb.active)
    head_fill = PatternFill("solid", fgColor="D9E2F3")
    for name, header, rows in sheets:
        ws = wb.create_sheet(title=name)
        ws.append(header)
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.fill = head_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
        width = [max(10, len(str(h)) * 2 + 4) for h in header]
        for row in rows:
            ws.append(row)
            for i, value in enumerate(row):
                width[i] = max(width[i], min(40, len(str(value)) * 2 + 2))
        for i, w in enumerate(width, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A2"
    path = os.path.join(OUT_DIR, filename)
    wb.save(path)
    return path


def write_text(filename, content):
    path = os.path.join(OUT_DIR, filename)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content.strip() + "\n")
    return path

# ---------------------------------------------------------------- D-01 员工手册（PDF）

def d01_employee_handbook():
    chapters = [
        ("第一章 总则", [
            "§1.1 目的",
            "为规范公司人力资源管理，明确员工的权利与义务，营造公平、有序的工作环境，特制定本手册。",
            "§1.2 适用范围",
            "本手册适用于星海智联科技有限公司（以下简称“公司”）全体正式员工与试用期员工。",
            "§1.3 生效与解释",
            "本手册自 2026 年 1 月 1 日起施行，由人力资源部负责解释与修订。",
        ]),
        ("第二章 工作时间与考勤", [
            "§2.1 标准工作时间",
            "公司标准工作时间为每周一至周五 9:00—18:00，午休时间为 12:00—13:30。",
            "§2.2 弹性打卡",
            "公司实行弹性打卡：每日 8:30—10:00 之间到岗均可，下班时间相应顺延，保证每日在岗满 8 小时。",
            "§2.3 补卡与迟到",
            "补卡次数、迟到认定与处理标准详见《考勤与假期管理规定》第 2 条。",
            "§2.4 其他考勤要求",
            "打卡方式、迟到处理、各类假别申请流程详见《考勤与假期管理规定》。",
        ]),
        ("第三章 休假制度", [
            "§3.1 年假标准",
            "员工累计工作满 1 年不满 10 年的，每年享有 5 天年假；满 10 年不满 20 年的，每年享有 10 天年假；满 20 年以上的，每年享有 15 天年假。",
            "§3.2 试用期与转正后的年假",
            "试用期员工不享受年假。员工转正后，当年度年假按转正后剩余日历天数折算，折算后不足 1 天的部分不计入。",
            "§3.3 年假申请",
            "年假需提前 3 个工作日通过 OA 系统提交申请，由直属上级审批。",
            "§3.4 年假结转",
            "年假原则上当年使用，最多可结转 5 天至次年 3 月 31 日前使用，逾期作废。",
            "§3.5 其他假别",
            "病假、事假、婚假、产假等假别的规定见《考勤与假期管理规定》。",
        ]),
        ("第四章 薪酬与福利", [
            "§4.1 工资发放",
            "公司以自然月为计薪周期，每月 15 日发放上一个自然月工资；遇法定节假日提前至最近一个工作日发放。",
            "§4.2 社会保险与公积金",
            "公司依法为员工缴纳社会保险与住房公积金，由人力资源部按月申报。",
            "§4.3 健康体检",
            "公司为转正员工提供每年一次免费体检。",
            "§4.4 加班与调休",
            "加班需提前申请，经批准后方可计入调休；调休应在 6 个月内使用完毕。",
        ]),
        ("第五章 保密与行为规范", [
            "§5.1 信息安全",
            "员工须遵守《IT 运维安全规范》，妥善保管账号与设备。",
            "§5.2 保密义务",
            "客户资料、合同文本、源代码等均属于公司保密信息，未经授权不得对外提供或传播。",
            "§5.3 违规处理",
            "违反保密约定的，公司将依据劳动合同与相关制度追究责任。",
        ]),
        ("第六章 附则", [
            "§6.1 确认书",
            "员工入职时须签署《员工手册确认书》，签署后视为已知悉并同意遵守本手册全部条款。",
            "§6.2 冲突处理",
            "本手册与公司其他制度不一致的，以本手册为准；本手册未尽事宜按国家法律法规执行。",
        ]),
    ]
    return build_pdf("01_员工手册.pdf", "员工手册（2026 版）", COMPANY + " · 人力资源部发布 · 第 1 版", chapters)


# ---------------------------------------------------------------- D-06 入职培训指南（PDF）

def d06_onboarding_guide():
    chapters = [
        ("第一章 入职流程", [
            "§1.1 报到当天",
            "新员工报到当天需完成：签署劳动合同、提交入职材料、领取工牌与办公设备、开通系统账号。",
            "§1.2 试用期",
            "新员工试用期为 3 个月。表现优秀者可由直属上级推荐，提前至 2 个月申请转正。",
        ]),
        ("第二章 转正流程", [
            "§2.1 提交申请",
            "员工应在试用期结束前 10 个工作日提交《转正申请表》。",
            "§2.2 审批流程",
            "转正审批共 5 个环节：员工提交申请 → 直属上级评估 → 部门负责人复核 → 人力资源部审批 → 结果通知，全程一般 5 个工作日完成。",
            "§2.3 转正后待遇",
            "转正后员工享受正式员工全部福利，包括年假、年度体检等，具体标准详见《员工手册》第三章。",
        ]),
        ("第三章 培训安排", [
            "§3.1 第一周",
            "入职引导与安全合规培训，时长 2 小时，由人力资源部组织。",
            "§3.2 第二至第四周",
            "岗位技能培训，由导师一对一带教，并在第一周内制定《试用期工作计划》。",
            "§3.3 第二个月",
            "产品与业务知识培训，结业考核 80 分及格，未通过者需在 2 周内补考。",
        ]),
        ("第四章 导师制", [
            "§4.1 导师职责",
            "每位新员工配 1 名导师，导师每月至少与学员进行 2 次一对一沟通，并填写辅导记录。",
            "§4.2 导师补贴",
            "导师补贴标准为每人每月 500 元，随当月工资发放。",
        ]),
        ("第五章 新员工常见问题", [
            "§5.1 试用期可以请假吗？",
            "可以。试用期员工的病假、事假按《考勤与假期管理规定》执行。",
            "§5.2 工牌丢失怎么办？",
            "到行政部补办，工本费 30 元，从当月工资中扣除。",
            "§5.3 设备出现问题找谁？",
            "在 IT 工单系统提交报修工单，服务时限见《客户支持服务流程》。",
        ]),
    ]
    return build_pdf("06_入职培训指南.pdf", "新员工入职培训指南", COMPANY + " · 人力资源部 · 2026 年 1 月", chapters)


# ---------------------------------------------------------------- D-02 产品介绍（Word）

def d02_product_intro():
    blocks = [
        ("h1", "一、产品定位"),
        ("p", "星海智答（V3.2）是面向企业客户服务场景的智能客服平台，通过大模型与知识库检索技术，"
              "帮助企业降低客服人力成本、提升首次解决率。产品定位为“开箱即用的企业级智能客服底座”。"),
        ("h1", "二、核心功能"),
        ("li", "知识问答：基于企业知识库自动回答客户咨询，答案可溯源到原始文档。"),
        ("li", "工单自动分类：根据问题描述自动识别工单类型与优先级，V3.2 版本分类准确率达到 92%。"),
        ("li", "坐席辅助：实时向人工坐席推荐标准话术与相关知识条目。"),
        ("li", "服务数据看板：展示咨询量、首次解决率、平均处理时长等指标。"),
        ("h1", "三、技术架构"),
        ("p", "产品采用“文档解析 + 向量检索 + 大模型生成”三层架构：文档经解析切片后写入向量库，"
              "用户提问时先做语义检索并重排序，再将高质量片段交给大模型生成答案。"),
        ("h1", "四、版本功能对比"),
        ("table", ["版本", "工单分类准确率", "知识问答", "坐席辅助"],
         [["V3.0", "78%", "支持", "不支持"],
          ["V3.1", "85%", "支持", "支持"],
          ["V3.2", "92%", "支持（带引用溯源）", "支持（话术推荐）"]]),
        ("h1", "五、客户案例"),
        ("p", "华东某电商客户上线星海智答后，客服人力投入下降约 30%，客户咨询平均响应时间从 45 秒缩短到 8 秒。"),
        ("h1", "六、服务与支持"),
        ("p", "产品相关的故障报修与技术支持，按照《客户支持服务流程》执行。"),
    ]
    return build_docx("02_产品介绍_智能客服平台.docx", "星海智答·智能客服平台产品介绍", COMPANY + " · 产品部 · V3.2", blocks)


# ---------------------------------------------------------------- D-07 客户支持服务流程（Word）

def d07_support_process():
    blocks = [
        ("h1", "一、适用范围"),
        ("p", "本流程适用于公司为客户提供的星海智答平台的技术支持服务，涵盖工单受理、处理、升级与关闭全过程。"),
        ("h1", "二、服务时间"),
        ("p", "常规技术支持时间为工作日 9:00—18:00；P0 级紧急问题提供 7×24 小时支持。"),
        ("h1", "三、工单等级与响应时限"),
        ("table", ["等级", "问题描述", "响应时限", "解决时限"],
         [["P0 紧急", "系统不可用、数据丢失", "30 分钟", "4 小时"],
          ["P1 高", "核心功能不可用、无规避方案", "2 小时", "1 个工作日"],
          ["P2 中", "部分功能异常、有规避方案", "4 小时", "3 个工作日"],
          ["P3 低", "咨询类、优化建议", "1 个工作日", "5 个工作日"]]),
        ("h1", "四、工单处理流程"),
        ("li", "第一步 提交：客户通过工单系统或服务邮箱提交问题，需附截图与操作路径。"),
        ("li", "第二步 受理与定级：客服在响应时限内确认受理，并按影响范围确定工单等级。"),
        ("li", "第三步 处理：技术工程师排查原因、给出方案并同步进展。"),
        ("li", "第四步 验证：客户验证处理结果，确认问题是否解决。"),
        ("li", "第五步 关闭：客户确认解决后关闭工单，并记录处理过程形成知识条目。"),
        ("h1", "五、升级机制"),
        ("p", "工单超过响应时限未响应的，系统自动升级至客服主管；升级后 2 小时仍无进展的，再升级至技术负责人。"),
        ("h1", "六、服务考核"),
        ("p", "客户成功部按月统计工单响应及时率与一次解决率，及时率目标为不低于 95%。"),
    ]
    return build_docx("07_客户支持服务流程.docx", "客户支持服务流程", COMPANY + " · 客户成功部 · 2026 年 2 月修订", blocks)

# ---------------------------------------------------------------- D-03 报销制度与费用标准（Excel）

def d03_reimbursement():
    sheets = [
        ("报销流程", ["步骤", "环节名称", "责任人", "要点", "时限要求"], [
            ["1", "填写并提交报销单", "报销人", "附发票原件、审批单、出差申请单", "出差结束后 10 个工作日内"],
            ["2", "部门经理审批", "部门经理", "确认业务真实性与预算归属", "2 个工作日"],
            ["3", "财务审核", "财务部", "审核发票合规性与金额标准", "3 个工作日"],
            ["4", "总经理审批", "总经理", "仅当单笔报销金额超过 5000 元时需总经理审批", "2 个工作日"],
            ["5", "财务打款", "财务部", "每月 25 日统一打款至员工工资卡", "——"],
        ]),
        ("差旅标准", ["城市类别", "住宿标准上限（元/晚）", "交通标准", "餐补（元/天）"], [
            ["一线城市（北京、上海、广州、深圳）", 500, "高铁二等座 / 经济舱", 100],
            ["二线城市（省会城市及计划单列市）", 400, "高铁二等座", 80],
            ["其他城市", 300, "高铁二等座", 60],
        ]),
        ("费用限额", ["费用类型", "限额标准", "备注"], [
            ["通讯补贴", "200 元/月", "随工资发放，无需报销"],
            ["办公用品", "单笔不超过 1000 元", "超出需部门负责人事前审批"],
            ["团建活动", "人均不超过 150 元/季度", "需提前提交活动方案"],
            ["市内打车", "22:00 以后可实报实销", "需附行程单说明事由"],
        ]),
        ("注意事项", ["序号", "说明"], [
            ["1", "发票抬头必须为公司全称“星海智联科技有限公司”，税号由财务部提供。"],
            ["2", "发票需为增值税发票，个人消费类发票、餐饮娱乐类发票不予报销。"],
            ["3", "出差前须提交出差申请，未提前申请的不予报销差旅费用。"],
            ["4", "住宿费超出标准的，超出部分由个人承担。"],
            ["5", "差旅类报销须在出差结束后 10 个工作日内提交；其他费用报销须在费用发生当月起的 3 个月内提交，逾期不予受理。"],
        ]),
    ]
    return build_xlsx("03_报销制度与费用标准.xlsx", sheets)


# ---------------------------------------------------------------- D-09 供应商对账明细（Excel，数值干扰项）

def d09_supplier_reconciliation():
    sheets = [
        ("对账明细", ["供应商名称", "对账月份", "应付金额（元）", "已付金额（元）", "未付金额（元）", "状态"], [
            ["杭州云图数据服务有限公司", "2026-01", 128000, 128000, 0, "已结清"],
            ["上海辰星印刷有限公司", "2026-01", 46500, 46500, 0, "已结清"],
            ["深圳恒芯电子有限公司", "2026-02", 238600, 200000, 38600, "部分付款"],
            ["杭州广联物流有限公司", "2026-02", 32400, 32400, 0, "已结清"],
            ["北京思远咨询有限公司", "2026-03", 96000, 0, 96000, "未付款"],
            ["苏州铭创模具制造有限公司", "2026-03", 175400, 100000, 75400, "部分付款"],
            ["杭州云图数据服务有限公司", "2026-03", 132000, 132000, 0, "已结清"],
            ["深圳恒芯电子有限公司", "2026-04", 246800, 0, 246800, "未付款"],
        ]),
        ("季度汇总", ["季度", "应付金额合计（元）", "已付金额合计（元）", "未付金额合计（元）"], [
            ["2026 年第一季度", 848900, 638900, 210000],
        ]),
    ]
    return build_xlsx("09_供应商对账明细.xlsx", sheets)


# ---------------------------------------------------------------- D-04 IT 运维安全规范（TXT）

def d04_it_security():
    content = """
IT 运维安全规范
星海智联科技有限公司 · 信息技术部 · 2026 年 3 月修订

1. 账号与密码
1.1 员工账号密码长度不得少于 12 位，且必须包含大写字母、小写字母、数字、特殊符号中的至少三类。
1.2 密码必须每 90 天更换一次，且不得与最近 3 次使用过的密码重复。
1.3 严禁共享账号，严禁将个人账号借给他人使用；因共享账号导致的安全事件由账号持有人承担责任。
1.4 系统管理员账号必须开启双因素认证。

2. 设备管理
2.1 公司配发的电脑严禁安装来源不明的软件，严禁关闭杀毒软件。
2.2 办公电脑离开工位时必须锁屏，锁屏快捷键为 Win + L。
2.3 员工离职当天须交回全部公司设备与门禁卡，由信息技术部核对后出具交接单。

3. 数据备份
3.1 业务数据库每日凌晨 2:00 执行一次增量备份。
3.2 每周日凌晨 2:00 执行一次全量备份。
3.3 备份数据保留 180 天，超期自动清理。
3.4 每季度开展一次备份恢复演练，演练记录归档保存。

4. 网络使用
4.1 禁止使用未经授权的 VPN 或代理工具访问外部网络。
4.2 访客网络仅限访问互联网，不得访问公司内部系统。
4.3 重要会议期间禁止使用个人热点处理涉密业务。

5. 安全事件处理
5.1 发现病毒、木马、数据泄露等安全事件，应在 2 小时内上报信息技术部。
5.2 上报渠道：IT 工单系统（服务时限见《客户支持服务流程》）或服务电话 0571-8888。
5.3 未及时上报导致损失扩大的，按公司相关规定处理。

6. 违规处理
6.1 违反本规范的行为，视情节轻重给予提醒、通报批评直至解除劳动合同的处理。
6.2 因违规造成公司损失的，公司有权依法追究赔偿责任。
    """
    return write_text("04_IT运维安全规范.txt", content)


# ---------------------------------------------------------------- D-08 考勤与假期管理规定（TXT，干扰项）

def d08_attendance():
    content = """
考勤与假期管理规定
星海智联科技有限公司 · 人力资源部 · 2025 年 12 月修订

1. 打卡规则
1.1 员工每日须打卡两次（上班卡、下班卡），打卡可通过办公区闸机或移动办公 App 完成。
1.2 忘记打卡的员工应在次月 3 日前提交补卡申请，每个自然月允许 3 次补卡。
1.3 因公外出无法打卡的，需在 OA 系统提交外出登记。

2. 迟到与早退
2.1 迟到 30 分钟以内且当月累计不超过 3 次的，不扣薪，但计入当月考勤记录。
2.2 当月累计迟到超过 3 次的，超出部分每次扣发当日工资的 10%。
2.3 无故早退按迟到同等标准处理。

3. 病假
3.1 请病假需提供二级以上医院开具的证明与病假条。
3.2 病假期间工资按本人日工资的 70% 发放，病假每年累计不超过 30 天。
3.3 连续病假超过 3 天的，需在返岗当日提交复岗申请。

4. 事假
4.1 事假为无薪假，每月累计不超过 3 天，全年累计不超过 15 天。
4.2 事假需提前 1 个工作日提交申请，紧急情况可事后 24 小时内补办。

5. 其他假别
5.1 婚假：员工本人结婚享有 10 天婚假，需提供结婚证复印件。
5.2 产假：女职工生育享有 158 天产假；男职工享有 15 天陪产假。
5.3 丧假：直系亲属去世享有 3 天丧假。
5.4 调休：加班调休应在 6 个月内使用完毕，逾期作废。

6. 说明
6.1 年假的标准、折算与结转规则见《员工手册》第三章，本规定不再重复说明。
6.2 本规定由人力资源部负责解释，自 2026 年 1 月 1 日起施行。
    """
    return write_text("08_考勤与假期管理规定.txt", content)


# ---------------------------------------------------------------- D-05 常见问题 FAQ（Markdown）

def d05_faq():
    content = """
# 员工常见问题 FAQ（2026 版）

> 编制：人力资源部 · 信息技术部 · 财务部　　更新日期：2026-03-01
> 本 FAQ 为高频问题的快速索引，具体标准以各项正式制度为准。

## 1. 如何申请年假？
在 OA 系统「我的假期」中选择年假，提前 3 个工作日提交，由直属上级审批。
年假的标准与折算规则见《员工手册》第三章。

## 2. 工资什么时候发放？
每月 15 日发放上一个自然月工资，遇节假日提前至最近一个工作日。

## 3. 报销需要准备哪些材料？
需要：报销单、发票原件、出差申请单（差旅类）、审批单。
单据需在费用发生当月起的 3 个月内提交，流程见《报销制度与费用标准》。

## 4. 如何申请 VPN 权限？
在 IT 工单系统提交「VPN 权限申请」，说明使用场景与期限，经直属上级与信息技术部审批后开通。
禁止使用未经授权的 VPN 或代理工具。

## 5. 忘记密码怎么办？
在登录页点击「忘记密码」，通过手机号验证码自助重置；如手机号已变更，请联系 IT 服务台（电话 0571-8888）人工重置。

## 6. 出差需要提前多久申请？
需提前 3 个工作日提交出差申请，未提前申请的不予报销差旅费用。
住宿与餐补标准见《报销制度与费用标准》「差旅标准」工作表。

## 7. 办公设备报修怎么办？
在 IT 工单系统提交报修工单，紧急程度与响应时限见《客户支持服务流程》。

## 8. 转正之后年假怎么算？
转正当年度年假按转正后剩余日历天数折算，不足 1 天不计；次年按完整年度标准享受。
试用期期间不享受年假。

## 9. 从哪里查看公司最新的制度文件？
所有制度文件统一存放在企业知识库的「制度文件」目录中，可在问答系统中直接提问查询。

## 10. 如何申请会议室？
在 OA 系统的「会议室预订」中选择时间与房间，超过 20 人的会议需提前 1 个工作日预订。
    """
    return write_text("05_常见问题FAQ.md", content)


# ---------------------------------------------------------------- D-10 公司简介与组织架构（Markdown）

def d10_company_profile():
    content = """
# 公司简介与组织架构

## 一、公司概况

| 项目 | 内容 |
| :--- | :--- |
| 公司全称 | 星海智联科技有限公司 |
| 成立时间 | 2015 年 6 月 |
| 总部地址 | 浙江省杭州市滨江区星光大道 88 号星海大厦 |
| 分支机构 | 深圳分公司、成都分公司 |
| 员工规模 | 420 余人 |
| 主营业务 | 企业智能客服与知识管理软件的研发与服务 |

## 二、主营业务

公司聚焦企业客户服务数字化，主要产品包括：

- 星海智答·智能客服平台（详见《产品介绍》）
- 星海知识库·企业知识管理系统
- 星海工单·客户服务工单系统

## 三、发展历程

| 时间 | 大事记 |
| :--- | :--- |
| 2015 年 6 月 | 公司在杭州成立，团队 12 人 |
| 2017 年 | 发布第一代客服机器人产品 |
| 2019 年 | 完成 A 轮融资，员工规模突破 100 人 |
| 2023 年 | 发布星海智答 V3.0，引入大模型能力 |
| 2026 年 | 员工规模达 420 余人，服务客户超过 600 家 |

## 四、组织架构

| 部门 | 主要职责 | 部门负责人职位 |
| :--- | :--- | :--- |
| 研发中心 | 产品研发、技术架构、运维保障 | 研发总监 |
| 产品部 | 产品规划、需求分析、产品设计 | 产品总监 |
| 客户成功部 | 客户支持、实施交付、客户培训 | 客户成功总监 |
| 市场部 | 品牌推广、市场活动、渠道合作 | 市场总监 |
| 人力资源部 | 招聘、培训、绩效、员工关系 | 人力资源总监 |
| 财务部 | 核算、报销、预算、税务 | 财务总监 |
| 行政部 | 办公环境、资产管理、后勤支持 | 行政经理 |

## 五、企业文化

- 价值观：客户第一、简单可信、长期主义
- 工作方式：小步快跑、以数据说话、当日事当日毕
- 人才理念：让优秀的人做有挑战的事
    """
    return write_text("10_公司简介与组织架构.md", content)


# ---------------------------------------------------------------- 入口

def main():
    register_cn_fonts()
    builders = [
        d01_employee_handbook,
        d02_product_intro,
        d03_reimbursement,
        d04_it_security,
        d05_faq,
        d06_onboarding_guide,
        d07_support_process,
        d08_attendance,
        d09_supplier_reconciliation,
        d10_company_profile,
    ]
    print("输出目录：%s" % OUT_DIR)
    for builder in builders:
        path = builder()
        size = os.path.getsize(path)
        print("  生成 %-42s %8.1f KB" % (os.path.basename(path), size / 1024.0))
    print("完成，共 %d 份示例文档。" % len(builders))


if __name__ == "__main__":
    main()