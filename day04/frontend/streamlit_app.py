"""智能客服系统 - Streamlit 前端（第4天课程代码）

运行（仓库根目录，需先启动后端 day04.main:app --port 8004）：
    streamlit run day04/frontend/streamlit_app.py
"""
import json
import uuid

import requests
import streamlit as st

# ---------- 后端地址（第4天的服务） ----------
API_BASE = "http://localhost:8004"

WELCOME = (
    "👋 您好！我是智能客服小秋秋，很高兴为您服务！\n\n"
    "我可以帮您：\n"
    "📦 查询订单状态\n"
    "📱 查询产品信息\n"
    "🚚 查询物流进度\n"
    "📞 转接人工客服"
)

st.set_page_config(page_title="🤖 智能客服系统", page_icon="💬", layout="centered")
st.title("🤖 智能客服系统")
st.caption("💡 第4天演示：FastAPI + DeepSeek + Function Calling + 流式输出")

if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": WELCOME}]
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())[:8]
if "pending_prompt" not in st.session_state:
    st.session_state.pending_prompt = None


def call_stream_api(prompt: str, container) -> str:
    """调用后端流式接口，并把内容实时渲染到 container 中"""
    full_response = ""
    response = requests.post(
        f"{API_BASE}/api/chat/stream",
        json={"message": prompt, "session_id": st.session_state.session_id, "temperature": 0.7},
        stream=True,
        timeout=120,
    )
    if response.status_code != 200:
        msg = f"请求失败：HTTP {response.status_code}"
        container.markdown(msg)
        return msg

    for line in response.iter_lines():
        if not line:
            continue
        line_str = line.decode("utf-8")
        if not line_str.startswith("data: "):
            continue
        try:
            data = json.loads(line_str[6:])
        except json.JSONDecodeError:
            continue
        content = data.get("content", "")
        if content == "[DONE]":
            break
        full_response += content
        container.markdown(full_response + "▌")
    container.markdown(full_response)
    return full_response


with st.sidebar:
    st.markdown("### 🔧 设置")
    st.markdown(f"**会话ID**: `{st.session_state.session_id}`")
    if st.button("🔄 重置对话", use_container_width=True):
        try:
            requests.post(
                f"{API_BASE}/api/chat/reset",
                params={"session_id": st.session_state.session_id},
                timeout=5,
            )
            st.session_state.messages = [{"role": "assistant", "content": "👋 对话已重置，有什么可以帮您的？"}]
            st.rerun()
        except Exception as e:
            st.error(f"重置失败: {str(e)}")

    st.markdown("---")
    st.markdown("### 💡 示例提问")
    for ex in ["帮我查一下订单ORD001", "iPhone 15 Pro多少钱？", "订单ORD002的物流到哪了？", "转人工客服"]:
        if st.button(ex, key=ex, use_container_width=True):
            st.session_state.pending_prompt = ex
            st.rerun()

    st.markdown("---")
    st.markdown("### 📊 系统状态")
    try:
        resp = requests.get(f"{API_BASE}/api/health", timeout=2)
        if resp.status_code == 200:
            st.success("✅ 后端服务正常")
        else:
            st.error(f"❌ 后端异常 ({resp.status_code})")
    except Exception:
        st.error("❌ 后端服务未启动")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

prompt = st.chat_input("请输入您的问题...")
if not prompt and st.session_state.pending_prompt:
    prompt = st.session_state.pending_prompt
    st.session_state.pending_prompt = None

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        container = st.empty()
        try:
            reply = call_stream_api(prompt, container)
        except Exception as e:
            reply = f"连接失败: {str(e)}"
            st.error(reply)
        if reply:
            st.session_state.messages.append({"role": "assistant", "content": reply})
