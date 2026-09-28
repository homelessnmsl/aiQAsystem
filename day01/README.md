# day01 —— FastAPI 入门 + DeepSeek 接入（第1天课程代码）

> 对应第1周任务：**W1-12**（课程代码）、**W1-13**（统一响应封装 / Pydantic 模型）、**W1-14**（大模型基类 + `/api/chat` 同步对话）

## 一、文件结构

```
day01/
├── main.py                          # 主程序：路由 + 统一响应 + 异常处理 + /api/chat + 课后作业
├── services/
│   └── llm/
│       ├── __init__.py              # 包入口，对外暴露 BaseLLM / DeepSeekAdapter
│       ├── base.py                  # 大模型抽象基类 BaseLLM（课程 7.2.1）
│       └── deepseek_adapter.py      # DeepSeek 适配器 DeepSeekAdapter（课程 7.2.2）
└── README.md
```

## 二、运行方式

先确保已完成环境准备（仓库根目录，见根 README）：

```powershell
python -m venv .venv             # 已创建则跳过（本机已用 Python 3.12 创建）
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env           # 填入 DEEPSEEK_API_KEY
```

启动服务（**在仓库根目录执行**）：

```powershell
uvicorn day01.main:app --reload
```

打开：

| URL | 说明 |
| :--- | :--- |
| http://127.0.0.1:8000/ | 根路由 |
| http://127.0.0.1:8000/docs | Swagger 交互式文档（用于验收测试） |

DeepSeek 连通性自测（课程练习6）：

```powershell
python -m day01.main
```

> 说明：本包使用相对导入（`from .services.llm import ...`），因此请使用
> `uvicorn day01.main:app` 或 `python -m day01.main` 运行，不要直接 `python day01/main.py`。

## 三、接口一览

| 方法 | 路径 | 说明 | 对应课程 |
| :--- | :--- | :--- | :--- |
| GET | `/` | 根路由 | 3.2 |
| GET | `/hello/{name}` | 路径参数 | 4.1 |
| GET | `/user/{user_id}` | 路径参数 + 类型转换 + HTTPException | 4.1 / 练习2 |
| GET | `/products?category=&page=` | 查询参数 | 练习2 |
| GET | `/chat?q=&session_id=&page=` | 查询参数示例 | 4.2 |
| POST | `/echo` | 请求体示例 | 5.3 |
| POST | `/api/echo` | 封装 echo 服务接口 | 练习5 |
| POST | `/api/say` | POST + Pydantic 模型 | 练习3 |
| POST | `/api/chat` | **同步对话（DeepSeek）** | 练习7 / 8.1 |
| POST | `/api/register` | 用户注册（用户名/密码长度、邮箱校验） | 作业1 |
| GET | `/api/user/{user_id}` | 获取用户信息（user_id<1 返回业务错误） | 作业2 |

### 统一响应格式（团队规范）

```json
{ "code": 0, "message": "success", "data": { } }
```

- `code = 0` 表示成功；`code ≠ 0` 表示业务错误，且 **HTTP 状态码与 code 一致**（400/404/500）。
- 说明：课程示例中字段名为 `msg`；本项目按团队接口规范（需求文档 FR-OPS-01）统一为 `message`。

### `/api/chat` 请求示例

```json
{
    "message": "你好，我想咨询退换货流程",
    "session_id": "session_001",
    "temperature": 0.7
}
```

响应示例：

```json
{
    "code": 0,
    "message": "success",
    "data": { "reply": "您好！关于退换货流程……", "session_id": "session_001" }
}
```

## 四、验收对照

### 随堂练习

- [x] 练习1 搭建项目环境：`/` 返回 `{"message":"智能客服系统运行中"}`，`/docs` 可打开
- [x] 练习2 路径参数 + 查询参数：`/user/123` 正常；`/user/abc` 返回 400 校验错误；`/products?category=手机&page=2` 正常
- [x] 练习3 POST + Pydantic：`/api/say` 缺省用户名为"匿名"
- [x] 练习4 统一响应格式 + 全局异常处理：所有接口返回 `{code, message, data}`
- [x] 练习5 `/api/echo` 返回 `{code:0, message:"success", data:{echo:"你说了：..."}}`
- [x] 练习6 接入 DeepSeek：`python -m day01.main` 输出模型回复（需配置 `.env`）
- [x] 练习7 `/api/chat`：Swagger 中输入"你好"返回 DeepSeek 回复

### 课后作业

- [x] 作业1 `POST /api/register`：合法请求返回 `{code:0, ..., data:{user_id:1, username:...}}`；
      `email: "test"` / `username: "ab"` 返回 400 校验失败
- [x] 作业2 `GET /api/user/1` 返回用户信息；`GET /api/user/0` 返回 `{code:400, message:"用户ID无效", data:null}`
- [x] 作业3 `/api/chat` 参数校验：`temperature=2.5` → 400 "temperature参数必须在0-2之间"；
      `message=""` → 400 "消息内容不能为空"；正常请求返回 DeepSeek 回复

## 五、离线自测（无需 API Key）

```powershell
python -m pytest tests/test_day01_offline.py
```

## 六、第1周代码地图（day01 ~ day05）

| 课程 | 内容 | 代码位置 |
| :--- | :--- | :--- |
| day01 | FastAPI 入门 + DeepSeek + 统一响应 + 基类 | `day01/`（本目录） |
| day02 | 多轮对话 + System Prompt | `day02/` |
| day03 | Function Calling 工具调用 | `day03/` |
| day04 | 流式输出（SSE）+ Streamlit 前端 | `day04/` |
| day05 | 配置集中管理 + 项目整合 | `day05/` |

> 课程代码 `day01~day05/` 与主工程解耦（架构设计 4.1）；
> 团队项目正式后端骨架在 `app/`，接口契约见 `docs/接口文档.md`。
