# app —— 企业知识库智能问答系统 · 后端骨架（第1周交付）

> 对应任务：**W1-13**（FastAPI 骨架：路由 / 统一响应封装 / Pydantic 模型）、
> **W1-14**（DeepSeek 对接：大模型基类 + `/api/chat` 同步对话）
> 接口契约：`docs/接口文档.md`（字段以此为准，先改文档再改代码）
> 目录规范：`docs/架构设计.md` 第 4 章；配置清单：第 9.5 节

## 一、第1周实现清单（对照接口文档）

| 项 | 状态 | 位置 |
| :--- | :--- | :--- |
| 应用入口：create_app / 路由注册 / 异常处理器挂载 | ✅ | `main.py` |
| 配置管理：.env → Settings（pydantic-settings，禁止散落 os.getenv） | ✅ | `core/config.py` |
| 统一响应：ApiResponse.ok / fail（`{code,message,data}`） | ✅ | `core/response.py` |
| 错误码总表（1.4）+ BizError + 全局异常处理器（不返回 Traceback） | ✅ | `core/errors.py` |
| 日志格式 / trace_id（tr_年月日_6位）/ Key 脱敏 sk-**** | ✅ | `core/logging.py` |
| API-02 `POST /api/chat`：多轮对话（最近 10 轮）、session_id 缺省自动新建 | ✅ | `api/chat.py` |
| API-02 可选 `stream=true`：SSE（事件格式对齐接口文档 2.11：delta → done/error） | ✅ | `api/chat.py` |
| API-01 `GET /api/health`：LLM 状态（其余依赖第2周接入，先返回 unconfigured） | ✅ | `api/health.py` |
| Pydantic 模型：ChatRequest / ChatResponse / Usage（逐字对齐第 3 章） | ✅ | `models/chat.py` |
| BaseLLM + DeepSeekClient：超时 60s、重试 1 次、错误码 3001/3002/3003/3004 | ✅ | `services/llm.py` |
| 会话历史（内存版；第2~3周按架构 7.2 迁移 SQLite messages 表） | ✅ | `services/conversation.py` |
| 离线测试：契约字段 / 错误码 / 流式 / 多轮（53 条，无需 API Key） | ✅ | `../tests/` |

### 不在第1周范围（按计划属第2周）

- `/api/upload`、`/api/documents`、`/api/ask`（待 AD 的 `knowledge/` 与 Chroma 就绪后接入）
- SQLite 落库（conversations / messages / feedback）、健康检查中向量库等真实状态

## 二、运行

```powershell
# 1) 仓库根目录：激活环境（首次见根 README：python -m venv .venv）
.venv\Scripts\activate
pip install -r requirements.txt

# 2) 配置密钥：复制 .env.example 为 .env，填入 DEEPSEEK_API_KEY
copy .env.example .env

# 3) 启动（仓库根目录）
python -m uvicorn app.main:app --reload --port 8000

# 4) （可选）第4天课程演示前端：先启动 day05 后端再运行
streamlit run day05/frontend/streamlit_app.py
```

- Swagger 文档：http://127.0.0.1:8000/docs
- 未配置 Key 时服务仍可启动；`/api/chat` 返回 `code=3003`（对齐接口文档 SM-04，见"实现说明"）

## 三、接口摘要（第1周）

| 方法 | 路径 | 说明 |
| :--- | :--- | :--- |
| GET | `/` | 服务存活探针（统一响应） |
| GET | `/api/health` | 健康检查（API-01） |
| POST | `/api/chat` | 基础对话（API-02，W1-14 验收接口；`stream=true` 走 SSE） |

### 统一响应与错误码

```json
{ "code": 0, "message": "success", "data": { } }
```

- 成功：HTTP 200 + `code=0`；失败：HTTP 状态与 `code` 同时返回（接口文档 1.3 / 1.4）。
- 参数校验失败：HTTP 400 + `code=1001` + `data.errors[{field, reason}]`。
- 常用错误码：`1001` 参数校验 / `3001` 模型超时 / `3002` 限流 / `3003` 未配置密钥 / `5000` 内部错误。

### `/api/chat` 示例（接口文档 2.2）

```json
// 请求
{ "message": "你好", "session_id": null, "temperature": 0.7, "max_tokens": 1024, "stream": false }

// 响应
{
  "code": 0,
  "message": "success",
  "data": {
    "trace_id": "tr_20260928_b7c2e1",
    "session_id": "conv_20260928_7d2e10",
    "reply": "你好！我是企业知识库智能助手……",
    "model": "deepseek-chat",
    "usage": { "prompt_tokens": 32, "completion_tokens": 58, "total_tokens": 90 },
    "latency_ms": 2310,
    "created_at": "2026-09-28T15:20:11+08:00"
  }
}
```

## 四、离线测试（无需 API Key）

```powershell
python -m pytest tests/ -q
```

覆盖：day01~day05 课程代码冒烟、工具与 Agent 逻辑、app 契约字段、错误码映射、SSE 事件。

## 五、实现说明与取舍（评审用）

1. **启动行为**：结构 9.5 要求"必填缺失启动即报错"，接口文档 SM-04 要求"缺 Key 时调用返回 3003"。
   二者冲突，本实现按**接口文档**执行（启动打印中文警告、调用时报 3003），评审后可再定。
2. **默认系统提示词**：读取 PE 交付的 `prompts/system_chat.md`（W1-15）；文件缺失时使用内置兜底文本，
   保证离线可运行。第2周 `/api/ask` 使用 `prompts/system_rag.md` + `answer_template.md`。
3. **流式**：`/api/chat?stream=true` 已实现（课程 day04 能力沉淀）；正式流式接口 `/api/ask` 按计划第3周接入。
4. **会话**：第1周为进程内内存实现；第2周按架构 7.2 迁移 SQLite（`repository.py`）。
5. **依赖**：沿用 AD 的版本锁定（requirements.txt），补充 `email-validator`、`python-dotenv`（课程代码依赖）。
