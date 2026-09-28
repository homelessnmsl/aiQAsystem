# web/ —— Streamlit 前端（UI 智能体交互工程师主责）

企业知识库智能问答系统的界面层。**只通过 HTTP 调用后端**，不 import 后端代码、不读写数据库（架构 3.2 依赖铁律）。

## 目录结构

```text
web/
├─ app.py                    # 问答页（主页）：提问框 + 对话流 + 引用区 + 反馈 + 演示模式
├─ pages/
│  └─ 1_知识库管理.py         # 上传页/知识库管理页：上传、进度、文档列表、删除
├─ components/
│  ├─ citations.py           # 引用折叠条、[n] 序号高亮、检索详情、反馈按钮
│  └─ states.py              # 空态/加载态/错误态/兜底态/三态徽章/后端状态灯
├─ api_client.py             # 统一 HTTP 客户端：拆 {"code","message","data"}、错误码→中文提示
├─ data/demo_answers.json    # 演示模式预置问答（断网可演示，FR-UI-05）
├─ selftest.py               # 前端骨架自测（AppTest，22 项，不需要后端）
└─ contract_check.py         # 接口契约回放自测（按 docs/接口文档.md 示例 JSON，10 项）
```

配套文件：`.streamlit/config.toml`（主题与端口）、`docs/页面原型.md`（W1-17 原型）、`docs/prototype/ui-prototype.html`（可点击原型）。

## 启动

```bash
# 1) 依赖（第1周根目录 requirements.txt 未就绪时可先单独安装）
pip install streamlit requests

# 2) 启动前端（在仓库根目录执行）
python -m streamlit run web/app.py
# 浏览器打开 http://127.0.0.1:8501
```

后端未启动时前端**不会崩溃**：会在侧栏提示"后端未连接"，并引导打开左侧「演示模式」；
演示模式下可完整走通"提问 → 答案 → 引用展开 → 反馈"，用于答辩现场断网演示。

## 与后端联调

| 环境变量 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `WEB_API_BASE` | `http://127.0.0.1:8000` | 后端地址，也可在页面侧栏临时修改 |
| `WEB_API_TIMEOUT_SECONDS` | `120` | 问答请求超时（答案生成 ≤10s，留足重试余量） |
| `MAX_FILE_SIZE_MB` / `MAX_FILES_PER_UPLOAD` | `20` / `5` | 上传限制，与后端保持一致 |

接口与字段假设见 `docs/页面原型.md` 第 7 节；`api_client.py` 对同义字段（`answer`/`reply`/`content` 等）做了兼容取值，
并在字段缺失时给默认值，**接口文档定稿前不会因为字段名差异把页面打崩**。

## 自测（W1-18 验收）

```bash
python web/selftest.py         # 页面与交互（AppTest，22 项）
python web/contract_check.py   # 接口字段解析（假后端回放，10 项）
```

覆盖：空态/示例问题/提问框、后端未启动的错误态与重试、演示模式答案与引用折叠条、
无依据兜底、知识库页上传区与空态、`api_client` 的响应拆包与中文错误映射、上传前置校验（格式/大小/数量）。

## 第1周范围说明

- 本页只做**骨架与交互**：真实上传/检索/生成由 DEV/AD 在第2周交付 `/api/upload`、`/api/ask` 后接入；
- 会话历史（FR-CONV）与流式回答（SSE）按计划在第3周实现，侧栏与加载态已预留位置；
- 演示模式预置问答数据取自 RA 的 `tests/sample_docs/` 虚构企业文档，仅供演示，不含任何真实企业信息。