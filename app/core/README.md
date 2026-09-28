# app/core/ —— 基础设施（最底层，不依赖任何上层模块）

- 主责：DEV（AD 定规范）　｜　规范：`docs/架构设计.md` 第 5、9 章

| 文件 | 职责 | 要点 |
| :--- | :--- | :--- |
| `config.py` | `.env → Settings`（pydantic-settings） | 变量清单见架构设计 9.5；必填缺失**启动即报错**并给中文提示 |
| `response.py` | `ApiResponse.ok(data)` / `fail(code, message)` | 统一 `{"code","message","data"}`（FR-OPS-01） |
| `errors.py` | 错误码常量 + 业务异常 + 全局异常处理器 | 错误码表见 `docs/接口文档.md` 1.4；禁止返回 Traceback |
| `logging.py` | 日志格式、`trace_id` 注入、Key 脱敏 | 脱敏为 `sk-****`；日志落 `data/logs/app.log` |

约定：其他模块一律 `from app.core.config import settings`，**禁止**在业务代码里散落 `os.getenv`。
