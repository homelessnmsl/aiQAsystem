# prompts/ —— Prompt 模板与说明文档（PE · W1-15 交付物）

| 项目信息 | 内容 |
| :--- | :--- |
| 交付任务 | W1-15「Prompt 初版：企业客服问答场景 Prompt（含系统提示词）」 |
| 负责人 | PE Prompt 工程师（姓名待组长填写） |
| 版本 | v1.0（2026-09-28，首版） |
| 关联需求 | UC-11、FR-QA-01/04/05/07、FR-CIT-01/02/04、FR-OPS-01、NFR-U-02、Q-03 |
| 关联文档 | `docs/需求文档_v1.md`（1.4 指标、7.3 评测集）、`docs/架构设计.md`、`docs/接口文档.md`（2.2 / 2.6） |
| 关联评测集 | `tests/qa_dataset_v1.json`（20 条，说明见 `docs/评测集说明_v1.md`） |
| 评审 | 10-04 周会评审；通过后由 DEV 于第 2 周接入 `/api/ask` |

## 1. 文件清单

| 文件 | 用途 | 使用场景 | 状态 |
| :--- | :--- | :--- | :--- |
| `system_chat.md` | 基础对话系统提示词（企业客服人设，不编造制度事实） | 第 1 周 `POST /api/chat`（UC-11） | 已完成 |
| `system_rag.md` | 知识库问答系统提示词（只依据检索片段、必须引用、无依据兜底） | 第 2 周起 `POST /api/ask` | 已完成 |
| `answer_template.md` | 用户侧问答模板：注入 `${history}` `${context}` `${question}`，约束答案格式 | `POST /api/ask` 默认使用 | 已完成 |
| `answer_template_json.md` | 同上的 JSON 结构化输出变体（含 `answer_type`、`citation_ids`） | `POST /api/ask`（备选，联调时选型） | 备选 |
| `few_shot_v1.md` | 3 条 Few-shot 示例（正常引用 / 表格多档 / 无依据兜底） | 第 2 周效果调优时按需启用 | 备选 |
| `README.md` | 本说明：变量约定、上下文格式、接入指引、长度预算、版本记录 | —— | 已完成 |

命名约定：提示词内容文件用 `.md`（纯文本内容、便于 Gitee 在线阅读与 diff 评审），文件名不带版本号，版本在本文第 6 节登记。

## 2. 变量与占位符约定

| 占位符 | 含义 | 注入方（第 2 周 DEV） | 缺省处理 |
| :--- | :--- | :--- | :--- |
| `${history}` | 历史对话（建议最近 3 轮，user / assistant 交替） | 会话模块 / `app/services/rag.py` | 「（无）」 |
| `${context}` | 检索片段（编号 [1]~[5]，含来源与位置） | `app/services/retrieval.py` | 传「（空）」并直接走兜底分支 |
| `${question}` | 本轮用户问题原文（未改写） | `app/api/ask.py` | 必填，1~500 字（超限返回 1004） |

1. 占位符统一为 `${name}`，渲染请用 `string.Template` 的 `safe_substitute`；**不要用 `str.format`**（JSON 变体含 `{}`，会抛错）。
2. 编号上下文 `[1]~[5]` 由**程序**生成，Prompt 只声明「只能引用给定编号」，不自行编号。
3. Render 后的提示词中不要残留未替换的 `${...}`，程序侧应加一次断言或日志检查。

## 3. 上下文（${context}）渲染格式 —— 与 W2-04 实现对齐（2026-10-08）

编号上下文由 `app/services/retrieval.py::build_context()` 生成，为「`[n] 来源：文件名（位置）` + 正文」两行块；Prompt 只声明“只能引用给定编号”，不自行编号：

```text
[1] 来源：01_员工手册.pdf（第 3 页）
员工累计工作满 1 年不满 10 年的，每年享有 5 天年假……

[2] 来源：03_报销制度与费用标准.xlsx（工作表「差旅标准」第 2~4 行）
一线城市（北京、上海、广州、深圳）住宿标准上限 500 元/晚……
```

1. 序号从 1 连续编号、最多 5 条（`TOP_K`），按相关性从高到低；`retrieve()` 已按 `SCORE_THRESHOLD`（当前 0.485）过滤，无命中时直接走 `not_found` 兜底（不调用大模型，省时延与费用）；
2. 「位置」由 `app/knowledge/metadata.py::format_location()` 生成：页码（PDF/Word）→ 工作表 + 行号（Excel）→ 行号区间（TXT）→ 章节标题（Markdown）；
3. 片段正文取原文，不改写、不翻译；整体按 `MAX_CONTEXT_TOKENS × 1.5`（汉字）预算拼接，超预算时丢弃低分片段（不截断正文）；
4. 引用列表由程序按 `build_citations()` 生成（ADR-06）：模型只负责在答案中写 `[n]`，不得输出文件名；DEV 接入 `/api/ask` 时按此实现。

> 验证记录：2026-10-08 首轮评测（`docs/评测报告_v1.md`）中 15 条可答题的引用编号与片段一一对应。

## 4. 接入指引（第 2 周 DEV）

```python
from pathlib import Path
from string import Template

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"

system_prompt = (PROMPTS / "system_rag.md").read_text(encoding="utf-8")
template = Template((PROMPTS / "answer_template.md").read_text(encoding="utf-8"))
user_content = template.safe_substitute(history="（无）", context=context_text, question=question)

messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": user_content},
]
```

多轮对话二选一（不要同时使用，避免历史重复注入）：

- 方案 A（推荐）：把历史消息按 `{"role": "user" / "assistant"}` 追加在 system 之后（`${history}` 填「（无）」）；
- 方案 B：只发一条 user 消息，把历史压缩进 `${history}`（保留最近 3 轮，控制在 500 字内）。

调用参数建议（与 `docs/接口文档.md` 2.6 一致）：

| 参数 | 建议值 | 说明 |
| :--- | :--- | :--- |
| `temperature` | 0.2 | 制度问答要稳定、可复现 |
| `max_tokens` | 512 | 对应答案 ≤ 200 字 |
| 超时 / 重试 | 60s / 1 次 | NFR-R-02；失败返回 3001 |
| JSON 变体 | `response_format={"type": "json_object"}` | 解析失败时回退纯文本模板，禁止把解析异常暴露给用户 |

## 5. 长度预算（对齐 MAX_CONTEXT_TOKENS=3000）

| 组成 | 估算 | 说明 |
| :--- | :--- | :--- |
| 系统提示词 `system_rag.md` | 约 1000 字 | 固定开销 |
| 检索片段 `${context}` | 5 × ≤ 600 字 | 由 `TOP_K` 与切片长度决定 |
| 模板 + 历史 + 问题 | 约 400 字 | 历史超限时按轮次截断 |
| 合计 | 约 4400 字（约 2500~3000 token） | 联调时用真实 token 计数复核；超预算时**先丢最低分片段**，再截断片段正文 |

## 6. 版本记录

| 版本 | 日期 | 修改人 | 变更内容 | 评测结果 | 状态 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| v1.0 | 2026-09-28 | PE | 首版：基础对话 / 知识库问答系统提示词、问答模板、JSON 变体、Few-shot 示例与本文档 | 未评测（第 2 周随 RAG 联调首跑） | 待 10-04 周会评审 |
| v1.1 | 2026-10-08 | PE | 依据首轮评测（`docs/评测报告_v1.md`）：新增“多小问逐一回答 / 缺依据部分如实说明”与“不提前回答未提出的追问、同一会话不重复”两条规则；上下文格式与 W2-04 实现对齐（仅说明文档） | M-01 100%、M-02 100%（人工）、M-03 93.3%（人工）、M-04 100% | 已提交，待 10-15 周会复核 |
| v1.2（计划） | 10-12 ~ 10-18 | PE | 第 3 周：结合 Rerank 与多轮改写复评；补充多轮历史压缩指令；跟进引用位置标签粒度问题 | 见 `docs/质量报告.md` | 计划 |

变更规则：任何 Prompt 改动必须（1）说明改动原因与预期影响；（2）用 20 条评测集跑一轮对比；（3）在 PR 描述中附「修改前 / 修改后」指标；（4）更新本表。

## 7. 待确认事项（10-04 周会闭环）

| 编号 | 问题 | 本文档的默认处理 | 决策人 |
| :--- | :--- | :--- | :--- |
| Q-03 | 答案是否限制 200 字 | 是：Prompt 已按「≤ 200 字 + 要点式」编写，超长由前端折叠 | PE / PM |
| —— | 是否启用 JSON 结构化输出 | 默认关闭，保留 `answer_template_json.md` 备选 | DEV + PE |
| —— | 是否注入 Few-shot | 默认关闭（省 token）；首轮评测引用缺失率 > 15% 时启用 | PE |
| —— | 兜底话术措辞 | 采用 `system_rag.md` 固定话术；与接口文档 2.6 示例 B 措辞统一后同步 | PE + AD |
