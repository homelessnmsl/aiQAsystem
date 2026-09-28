"""第1天课程代码：FastAPI 入门 + DeepSeek 接入 + /api/chat 接口

覆盖课程内容：
- 3.x  第一个 FastAPI 应用、启动与验证
- 4.x  路由：路径参数（练习2）、查询参数（练习2）、请求体 + Pydantic（练习3）
- 5.x  统一响应格式 {code, message, data}（练习4）、echo 接口（练习5）、全局异常处理
- 6.x  DeepSeek API 接入（OpenAI 兼容 SDK，练习6）
- 7.x  大模型抽象基类 BaseLLM（7.2.1）+ DeepSeekAdapter 适配器（7.2.2）
- 8.x  /api/chat 同步对话接口（练习7）

课后作业：
- 作业1  POST /api/register         用户注册（用户名/密码长度、邮箱格式校验）
- 作业2  GET  /api/user/{user_id}   获取用户信息（user_id < 1 返回业务错误）
- 作业3  POST /api/chat             参数校验（temperature 0~2、消息不能为空）

启动（在仓库根目录执行）：
    uvicorn day01.main:app --reload
接口文档：
    http://127.0.0.1:8000/docs

DeepSeek 连通性自测（练习6）：
    python -m day01.main
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field

from .services.llm import BaseLLM, DeepSeekAdapter

# ---------- 加载环境变量（仓库根目录 .env，6.4节） ----------
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# ---------- 创建应用（3.2节） ----------
app = FastAPI(
    title="智能客服对话机器人",
    description="第1天：FastAPI 入门 + DeepSeek 接入（含课后作业）",
    version="1.0.0",
)

# ---------- 初始化大模型（7.x 基类 + 适配器） ----------
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
BASE_URL = os.getenv("BASE_URL", "https://api.deepseek.com/v1")

if not DEEPSEEK_API_KEY:
    print("[警告] 未检测到 DEEPSEEK_API_KEY，/api/chat 暂不可用；请复制 .env.example 为 .env 并填写 Key")
    llm: BaseLLM | None = None
else:
    llm = DeepSeekAdapter(api_key=DEEPSEEK_API_KEY, model=DEEPSEEK_MODEL, base_url=BASE_URL)
    print(f"[OK] DeepSeek API 配置成功（模型：{DEEPSEEK_MODEL}）")


# ============================================================
# 请求模型（4.3节 + 练习3 + 作业1）
# ============================================================
class ChatRequest(BaseModel):
    """对话请求体（8.1节）"""

    message: str = Field(..., min_length=1, description="用户消息")
    session_id: str | None = Field(None, description="会话ID（可选）")
    temperature: float = Field(0.7, ge=0, le=2, description="温度参数，0~2")


class UserMessage(BaseModel):
    """练习3：POST /api/say 请求体"""

    content: str = Field(..., description="消息内容")
    user_name: str = Field("匿名", description="用户名（可选，默认匿名）")


class UserRegister(BaseModel):
    """作业1：用户注册请求体"""

    username: str = Field(..., min_length=3, max_length=20, description="用户名，长度3-20")
    password: str = Field(..., min_length=6, max_length=20, description="密码，长度6-20")
    email: EmailStr = Field(..., description="邮箱地址")


# ============================================================
# 统一响应格式（5.2节）
# 团队规范：{code, message, data}，code=0 表示成功。
# （课程示例中字段名为 msg，本项目统一采用团队接口规范的 message）
# ============================================================
def success_response(data=None, message="success"):
    """成功响应"""
    return {"code": 0, "message": message, "data": data}


def error_response(code: int, message: str, data=None):
    """错误响应"""
    return {"code": code, "message": message, "data": data}


# 作业3：把指定字段的校验错误转成更友好的中文提示
FIELD_ERROR_MESSAGES = {
    "temperature": "temperature参数必须在0-2之间",
    "message": "消息内容不能为空",
}


# ============================================================
# 全局异常处理（5.4节）
# ============================================================
@app.exception_handler(RequestValidationError)
def validation_exception_handler(request: Request, exc: RequestValidationError):
    """捕获请求参数校验失败（统一为 400 + 统一响应格式）"""
    errors = [{"field": ".".join(str(x) for x in e["loc"]), "msg": e["msg"]} for e in exc.errors()]
    if errors:
        field = errors[0]["field"].split(".")[-1]
        if field in FIELD_ERROR_MESSAGES:
            return JSONResponse(
                status_code=400,
                content=error_response(400, FIELD_ERROR_MESSAGES[field], errors),
            )
    return JSONResponse(
        status_code=400,
        content=error_response(400, "请求参数校验失败", errors),
    )


@app.exception_handler(HTTPException)
def http_exception_handler(request: Request, exc: HTTPException):
    """捕获主动抛出的 HTTPException，统一响应格式"""
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(exc.status_code, str(exc.detail)),
    )


@app.exception_handler(Exception)
def global_exception_handler(request: Request, exc: Exception):
    """捕获所有未处理的异常"""
    return JSONResponse(
        status_code=500,
        content=error_response(500, f"服务器内部错误: {str(exc)}"),
    )


# ============================================================
# 基础路由（3.2 / 4.1 / 4.2 节 + 练习2）
# ============================================================
@app.get("/")
def root():
    """3.2节：根路由"""
    return success_response(data={"message": "智能客服系统运行中"})


@app.get("/hello/{name}")
def say_hello(name: str):
    """4.1节：路径参数"""
    return success_response(data={"message": f"你好，{name}！"})


@app.get("/user/{user_id}")
def get_user(user_id: int):
    """练习2：路径参数 + 自动类型转换（GET /user/abc 会返回参数校验错误）"""
    if user_id < 1:
        raise HTTPException(status_code=400, detail="用户ID必须大于0")
    if user_id > 100:
        raise HTTPException(status_code=404, detail="用户不存在")
    return success_response(data={"user_id": user_id, "name": f"用户{user_id}"})


@app.get("/products")
def get_products(category: str, page: int = 1):
    """练习2：查询参数（category 必填，page 可选默认1）"""
    return success_response(data={"category": category, "page": page, "items": []})


@app.get("/chat")
def chat_query(q: str, session_id: str | None = None, page: int = 1):
    """4.2节：查询参数示例 /chat?q=你好&session_id=001&page=1"""
    return success_response(data={"question": q, "session_id": session_id, "page": page})


# ============================================================
# 请求体相关路由（4.3 / 5.3 节 + 练习3 / 练习5）
# ============================================================
@app.post("/echo")
def echo(request: ChatRequest):
    """5.3节：请求体示例"""
    return success_response(data={"reply": f"你说的是：{request.message}"})


@app.post("/api/echo")
def api_echo(request: ChatRequest):
    """练习5：封装 echo 服务接口"""
    return success_response(data={"echo": f"你说了：{request.message}"})


@app.post("/api/say")
def say(request: UserMessage):
    """练习3：POST 请求 + Pydantic 模型"""
    return success_response(data={"reply": f"{request.user_name}说：{request.content}"})


# ============================================================
# 核心接口：/api/chat 同步对话（8.1节 + 作业3）
# ============================================================
@app.post("/api/chat")
def chat_api(request: ChatRequest):
    """
    智能客服对话接口（同步）

    请求体：
        - message: 用户消息（必填）
        - session_id: 会话ID（可选）
        - temperature: 温度参数（可选，默认0.7，范围0~2）
    """
    if llm is None:
        raise HTTPException(status_code=500, detail="大模型未初始化，请检查 API Key 配置")

    # 作业3：消息内容不能为空（去除首尾空白后判断）
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="消息内容不能为空")

    try:
        # 1. 构造消息列表（6.7节 role 说明）
        messages = [
            {"role": "system", "content": "你是一个智能客服助手，请用友好专业的语气回答用户问题。"},
            {"role": "user", "content": request.message},
        ]
        # 2. 调用大模型（8.1节）
        response = llm.chat(messages=messages, temperature=request.temperature)
        # 3. 提取回复
        reply = response.choices[0].message.content
        # 4. 返回统一格式
        return success_response(data={"reply": reply, "session_id": request.session_id})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"对话服务异常: {str(e)}")


# ============================================================
# 课后作业1：用户注册接口
# ============================================================
@app.post("/api/register")
def register(user: UserRegister):
    """作业1：POST /api/register 用户注册（演示用途，无数据库，固定返回 user_id=1）"""
    return success_response(data={"user_id": 1, "username": user.username})


# ============================================================
# 课后作业2：获取用户信息接口
# ============================================================
@app.get("/api/user/{user_id}")
def get_user_info(user_id: int):
    """作业2：GET /api/user/{user_id}，user_id 小于 1 返回业务错误 400"""
    if user_id < 1:
        raise HTTPException(status_code=400, detail="用户ID无效")
    return success_response(data={
        "id": user_id,
        "name": f"用户{user_id}",
        "email": f"user{user_id}@test.com",
    })


# ============================================================
# 练习6：DeepSeek 连通性自测（python -m day01.main）
# ============================================================
def test_deepseek() -> bool:
    """调用一次 DeepSeek，验证 API 是否打通"""
    print("=" * 52)
    print("[测试] DeepSeek API 连通性测试")
    if llm is None:
        print("[警告] 未配置 DEEPSEEK_API_KEY，跳过测试。")
        print("   请复制 .env.example 为 .env 并填入 Key 后重试。")
        return False
    try:
        response = llm.chat(messages=[
            {"role": "system", "content": "你是一个智能客服助手"},
            {"role": "user", "content": "你好，请用一句话介绍你自己"},
        ])
        print("[OK] 测试成功！")
        print(f"回复：{response.choices[0].message.content}")
        usage = getattr(response, "usage", None)
        if usage is not None:
            print(f"Token 用量：{usage.total_tokens}")
        return True
    except Exception as e:
        print(f"[失败] 测试失败：{e}")
        return False


if __name__ == "__main__":
    test_deepseek()
