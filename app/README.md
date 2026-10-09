# app —— 企业知识库智能问答系统 · 后端（第1~2周交付）

> 接口契约：`docs/接口文档.md`（字段以此为准，先改文档再改代码）
> 目录规范：`docs/架构设计.md` 第 4 章；配置清单：第 9.5 节

## 一、实现清单

### 第1周（W1-13 / W1-14，已并入 dev）

| 项 | 位置 |
| :--- | :--- |
| 应用入口 create_app / 路由注册 / 异常处理器挂载 | `main.py` |
| 配置管理（.env → Settings） | `core/config.py` |
| 统一响应 ApiResponse.ok / fail | `core/response.py` |
| 错误码总表（1.4）+ BizError + 全局异常处理器 | `core/errors.py` |
| 日志 / trace_id / Key 脱敏 | `core/logging.py` |
| API-02 `POST /api/chat`（多轮；可选 stream=true SSE） | `api/chat.py` |
| BaseLLM + DeepSeekClient（超时/重试/错误码 3001~3004） | `services/llm.py` |

### 第2周（W2-05 / W2-06 / W2-07，本分支）

| 项 | 状态 | 位置 |
| :--- | :--- | :--- |
| API-03 `POST /api/upload`：白名单/大小/数量校验 → 落盘 → 解析入库 → 台账；逐文件失败隔离；全部失败 2002 | ✅ | `api/upload.py` |
| API-04 `GET /api/documents`：分页/关键字/格式/状态过滤，字段对齐 2.4 | ✅ | `api/documents.py` |
| API-06 `POST /api/ask`：检索 → Prompt 渲染（PE 模板）→ 生成 → 引用装配 → 落库 | ✅ | `services/rag.py`、`api/ask.py` |
| 引用规则：citations 只保留答案实际引用的 `[n]`；未用编号 → 降级 not_found（架构 6.9）；对外编号连续 1..N（D2-02 方案B） | ✅ | `services/rag.py` |
| 兜底：无有效候选 / 空库 → 不调用 LLM（2001 / not_found，接口文档 2.6） | ✅ | `services/rag.py` |
| SQLite 台账：documents / conversations / messages（架构 7.2） | ✅ | `services/repository.py` |
| 检索明细扩展：retrieve_with_raw 返回 (raw, effective)，retrieved[] 供 PE 统计 M-01 | ✅ | `services/retrieval.py` |
| 健康检查升级：四项依赖真实状态 + 台账/向量库对账（不一致置 degraded） | ✅ | `api/health.py` |
| Pydantic 模型：UploadResult / PageData / AskRequest / Citation / Latency 等 | ✅ | `models/` |
| 建库脚本同步台账（`--rebuild` 同步清空台账），保证命令行与 API 两条路径一致 | ✅ | `scripts/init_kb.py`、`scripts/build_kb.py` |
| 离线测试：台账 CRUD、上传/文档/问答契约、错误码、降级规则 | ✅ | `../tests/` |

### 不在第2周范围（按计划属第3周）

- `/api/ask` 的 `stream=true`（SSE，2.11）、`clarify` 澄清、多轮问题改写
- `/api/documents/{doc_id}` 删除、`/api/feedback`、会话列表/详情（2.5/2.7/2.9/2.10）
- Rerank 默认启用与 A/B 调优（`use_rerank` 参数已预留，默认关闭）

## 二、运行

```powershell
# 1) 仓库根目录：激活环境（Python 3.12 + .venv，见根 README）
.venv\Scripts\activate
pip install -r requirements.txt

# 2) 配置密钥：复制 .env.example 为 .env，填入 DEEPSEEK_API_KEY
copy .env.example .env

# 3) 启动（仓库根目录）
python -m uvicorn app.main:app --reload --port 8000

# 4) 建库（二选一）：
#    a. 通过 API 上传（推荐，自动写台账）：Swagger /docs 中 POST /api/upload 传 1~5 个文件
#    b. 命令行导入样例：python scripts/init_kb.py           （与台账自动同步）
#       重建：python scripts/build_kb.py --rebuild --dir tests/sample_docs
```

- Swagger 文档：http://127.0.0.1:8000/docs
- 未配置 Key 时服务仍可启动；`/api/chat`、`/api/ask` 返回 `code=3003`（对齐 SM-04）
- 提示：首次检索请求会加载本地向量模型（约 10~15 秒），**演示前先预热一次提问**，之后单次检索 < 30ms

## 三、接口摘要（第1~2周）

| 方法 | 路径 | 说明 | 交付 |
| :--- | :--- | :--- | :--- |
| GET | `/api/health` | 健康检查：llm / embedding / vector_store / sqlite + 台账对账 | W1/W2 |
| POST | `/api/chat` | 基础对话（多轮；`stream=true` SSE） | W1 |
| POST | `/api/upload` | 上传 1~5 个文档并建库（逐文件结果，失败隔离） | W2-05 |
| GET | `/api/documents` | 文档台账列表（分页/过滤） | W2-06 |
| POST | `/api/ask` | RAG 问答：答案 + 引用 + 检索明细 | W2-07 |

### 统一响应与错误码（接口文档 1.2 / 1.4）

```json
{ "code": 0, "message": "success", "data": { } }
```

- 成功：HTTP 200 + `code=0`；失败：HTTP 状态与 `code` 同时返回。
- 常用：`1001` 参数校验（`data.errors[{field,reason}]`）/ `1002` 文件类型 / `1003` 文件超限 /
  `1004` 问题不合法 / `2001` 知识库为空 / `2002` 上传全部失败 / `3001` 超时 / `3003` 未配置密钥。

## 四、离线测试（无需 API Key / 不发起真实模型调用）

```powershell
python -m pytest tests/ -q
```

覆盖：day01~day05 课程代码、工具与 Agent、`/api/chat` 契约、LLM 错误码映射、
台账 CRUD、`/api/upload` 校验与失败隔离、`/api/documents` 过滤、`/api/ask` 引用/降级/落库。

## 五、联调自测记录（2026-10-08，DEV）

- **入库**：`tests/sample_docs/` 10 份文档经 `/api/upload` 实测：10/10 `success`，共 31 个切片；
  `/api/health` 四项依赖 `ok`，台账 10 文档 / 31 切片与向量库一致（SM-05/06/10）
- **问答**：`tests/qa_dataset_v1.json` 20 条经 `/api/ask` 全量跑通：20/20 成功、
  15 `answered` + 5 `not_found`（与数据集标注一致）；可答题 Top-1 来源命中 15/15
- **时延**（预热后）：端到端 avg 585ms / P95 1078ms；检索 avg 19ms（满足 M-05 预算）
- 冒烟清单 SM-01~SM-15 中第2周相关项均通过；SM-16 往后属第3周接口，未实现

## 六、实现说明与取舍（评审用）

1. **启动行为**：架构 9.5「必填缺失启动即报错」与接口文档 SM-04「缺 Key 时调用返回 3003」冲突，
   按接口文档执行（启动打印中文警告、调用时报 3003）。
2. **citations 生成规则**（架构 6.9）：程序依据答案中实际引用的 `[n]` 生成引用列表；
   越界编号剔除并记 WARN；模型未使用任何编号但返回实质答案 → 降级 `not_found`（宁可不答，不可编造）。
3. **not_found 分支不调用 LLM**，但 `retrieved[]` 仍返回原始 Top-K（PE 统计 M-01 需要）。
4. **台账一致性**（架构 6.6）：写入顺序 = 切片入库成功 → 台账 `success`；`/api/health` 对账
   台账切片总数与 Chroma count，不一致置 `degraded` 并告警；`scripts/*` 与 API 两条建库路径均已同步台账。
5. **`stream=true`（/api/ask）** 返回 1001 + "计划第3周交付"明确提示（2.11 约定第2周先非流式）。
6. **默认提示词**：`/api/chat` 用 PE 的 `prompts/system_chat.md`；`/api/ask` 用
   `prompts/system_rag.md` + `answer_template.md`（string.Template 渲染；文件缺失时内置兜底）。
