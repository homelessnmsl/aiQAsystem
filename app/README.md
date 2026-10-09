# app —— 企业知识库智能问答系统 · 后端（第1~3周交付）

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

### 第2周（W2-05 / W2-06 / W2-07，已并入 dev）

| 项 | 位置 |
| :--- | :--- |
| API-03 `POST /api/upload`：白名单/大小/数量校验 → 落盘 → 解析入库 → 台账；失败隔离 | `api/upload.py` |
| API-04 `GET /api/documents`：分页/关键字/格式/状态过滤 | `api/documents.py` |
| API-06 `POST /api/ask`：检索 → Prompt 渲染 → 生成 → 引用装配 → 落库 | `services/rag.py`、`api/ask.py` |
| 引用规则：citations 只保留答案实际引用的 `[n]`；未用编号 → 降级 not_found（架构 6.9） | `services/rag.py` |
| SQLite 台账：documents / conversations / messages（架构 7.2） | `services/repository.py` |
| 检索明细扩展：retrieve_with_raw 返回 (raw, effective) | `services/retrieval.py` |
| 健康检查：四项依赖 + 台账/向量库对账 | `api/health.py` |
| 建库脚本同步台账（init_kb / build_kb） | `scripts/` |

### 第3周（W3 DEV 交付，已并入 dev）

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
| API-08 `POST /api/feedback`：点赞/点踩（message_id 不存在 → 1005） | ✅ | `api/conversation.py` |
| API-09 `GET /api/conversations`：会话列表（标题/消息数/时间，分页 + keyword） | ✅ | `api/conversation.py` |
| API-10 `GET /api/conversations/{session_id}`：会话详情（含引用，回显恢复） | ✅ | `api/conversation.py` |
| API-11 `DELETE /api/conversations/{session_id}`：清空会话消息（幂等；同步清空进程内上下文） | ✅ | `api/conversation.py` |
| 多轮改写：省略式追问补全后再检索（架构 8.2 ①、FR-QA-05）；失败降级原文 | ✅ | `services/rag.py` |
| 历史恢复：内存为空时从 SQLite 恢复会话历史（服务器重启后仍可续聊） | ✅ | `services/rag.py` |
| feedback 表与索引（架构 7.2）+ 会话查询/清空台账方法 | ✅ | `services/repository.py` |
| API-05 `DELETE /api/documents/{doc_id}`：删向量 → 删原始文件 → 台账置 deleted；重复删除安全（1005）（W3-06） | ✅ | `api/documents.py` |
| 离线测试：会话/反馈/多轮改写/删除文档/降级（全量 125 条） | ✅ | `../tests/` |

### 仍不在范围（第3周看板待定 / 第4周）

- `/api/ask` 的 `stream=true`（SSE，2.11；W3-07 在途）与 `clarify` 澄清（2.6 实现提示 1，第4周）
- Rerank 默认启用与 A/B 调优（`use_rerank` 已预留；实测结论见架构 6.8，默认关闭；W3-04 扩容复核）

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
#    a. 通过 API 上传（推荐，自动写台账）：POST /api/upload 传 1~5 个文件
#    b. 命令行导入样例：python scripts/init_kb.py       （与台账自动同步）
#       重建：python scripts/build_kb.py --rebuild --dir tests/sample_docs
```

- Swagger 文档：http://127.0.0.1:8000/docs
- 未配置 Key 时服务仍可启动；`/api/chat`、`/api/ask` 返回 `code=3003`（对齐 SM-04）
- 提示：首次检索请求会加载本地向量模型（约 10~15 秒），**演示前先预热一次提问**，之后单次检索 < 30ms

## 三、接口摘要（第1~3周）

| 方法 | 路径 | 说明 | 交付 |
| :--- | :--- | :--- | :--- |
| GET | `/api/health` | 健康检查：四项依赖 + 台账对账 | W1/W2 |
| POST | `/api/chat` | 基础对话（多轮；`stream=true` SSE） | W1 |
| POST | `/api/upload` | 上传 1~5 个文档并建库 | W2-05 |
| GET | `/api/documents` | 文档台账列表（分页/过滤） | W2-06 |
| DELETE | `/api/documents/{doc_id}` | 删除文档及其向量与原始文件（重复删除安全） | W3-06 |
| POST | `/api/ask` | RAG 问答：答案 + 引用 + 检索明细（多轮改写） | W2-07 / W3 |
| POST | `/api/feedback` | 答案反馈（up/down + 备注） | W3 |
| GET | `/api/conversations` | 会话列表（分页 + 标题模糊） | W3 |
| GET | `/api/conversations/{session_id}` | 会话详情（消息 + 引用） | W3 |
| DELETE | `/api/conversations/{session_id}` | 清空会话消息（幂等） | W3 |

### 统一响应与错误码（接口文档 1.2 / 1.4）

```json
{ "code": 0, "message": "success", "data": { } }
```

- 成功：HTTP 200 + `code=0`；失败：HTTP 状态与 `code` 同时返回。
- 常用：`1001` 参数校验（`data.errors[{field,reason}]`）/ `1002` 文件类型 / `1003` 文件超限 /
  `1004` 问题不合法 / `1005` 资源不存在 / `2001` 知识库为空 / `2002` 上传全部失败 /
  `3001` 超时 / `3003` 未配置密钥。

## 四、离线测试（无需 API Key / 不发起真实模型调用）

```powershell
python -m pytest tests/ -q
```

覆盖：day01~day05 课程代码、工具与 Agent、`/api/chat` 契约、LLM 错误码映射、台账 CRUD、
`/api/upload` 校验与失败隔离、`/api/documents` 过滤、`/api/ask` 引用/降级/多轮改写/落库、
会话列表/详情/清空与反馈。

## 五、联调自测记录

**第2周（2026-10-08）**

- 10 份样例经 `/api/upload` 入库：10/10 成功、31 切片；健康检查四项依赖全绿、台账一致
- 评测集 20 条经 `/api/ask` 全量跑通：20/20 成功、15 answered + 5 not_found（与标注一致）

**第3周（2026-10-09，feature/conversations）**

- 会话列表：53 个真实会话（含 UI 联调数据）正常分页返回；详情含引用与 trace_id
- 反馈：对真实 assistant 消息点踩写入成功（`fb_20261009_*`）
- 多轮改写（真实 LLM）：第 1 轮"试用期有多久？"（无历史，不改写）→ 第 2 轮"那转正后呢？"
  被改写为"新员工转正后有什么变化？"后检索作答（改写耗时约 1.5s，含在 retrieval 段计时）
- 清空：`deleted_messages=4`，详情消息归零，进程内上下文同步清空
- 删除文档（真实链路）：临时文档上传 → 提问命中并引用 → 删除（`deleted_chunks=1`）→ **检索不再命中**、
  重复删除返回 1005、台账/向量库计数回到一致（31/10）（W3-06）

## 六、实现说明与取舍（评审用）

1. **启动行为**：架构 9.5「必填缺失启动即报错」与接口文档 SM-04「缺 Key 时调用返回 3003」冲突，
   按接口文档执行（启动打印中文警告、调用时报 3003）。
2. **citations 生成规则**（架构 6.9）：程序依据答案中实际引用的 `[n]` 生成引用列表；
   越界编号剔除并记 WARN；模型未使用任何编号但返回实质答案 → 降级 `not_found`（宁可不答，不可编造）。
3. **多轮改写**（架构 8.2 ①）：仅当会话有历史时调用一次 LLM 改写（temperature=0），
   改写结果进 `rewritten_question`；改写失败自动降级为原文检索，不影响主链路；
   历史注入当前为「用户：/助手：」文本（D2-04 实测方案），A/B 定版随 PE 复核。
4. **历史恢复**：会话历史优先取进程内缓存；为空时从 SQLite messages 恢复（服务器重启后仍可续聊）。
5. **清空会话**（Q-01 决议）：仅清空消息、保留会话行，返回 `deleted_messages`；幂等。
6. **反馈**：同一 message_id 可多次提交（不合并），保留完整反馈流水；message_id 不存在 → 1005。
7. **台账一致性**（架构 6.6）：写入顺序 = 切片入库成功 → 台账 `success`；`/api/health` 对账
   台账切片总数与 Chroma count，不一致置 `degraded` 并告警；`scripts/*` 与 API 建库路径均已同步台账。
8. **默认提示词**：`/api/chat` 用 PE 的 `prompts/system_chat.md`；`/api/ask` 用
   `prompts/system_rag.md` + `answer_template.md`（string.Template 渲染；文件缺失时内置兜底）。
7. **推理模型兼容（`reasoning_content`）**：`deepseek-v4-pro` 等推理模型会在响应中携带思维链，
   本系统一律**不对外返回、不落库、不参与后续请求拼接**（工具链路的助手消息清洗为
   role/content/tool_calls 规范结构）；流式输出只下发正文（思维链分片跳过）；
   若 `max_tokens` 被思维链耗尽（`finish_reason=length` 且正文为空）按 3004 返回明确提示。
   切换到推理模型时建议同步调大 `LLM_MAX_TOKENS`（思维链计入生成 token 预算）。
