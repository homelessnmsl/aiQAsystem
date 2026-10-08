# -*- coding: utf-8 -*-
"""接口契约回放自测（UI 主责）——用 `docs/接口文档.md` 的示例 JSON 验证前端解析。

思路：在本地起一个**假后端**，按接口文档原样返回示例响应，然后调用 `api_client`
逐个接口解析并断言。好处是不依赖真实后端、不需要 API Key，几秒钟即可回归。

运行（仓库根目录）：python web/contract_check.py
退出码 0 = 全部通过。

覆盖：/api/health、/api/ask、/api/documents、/api/upload、/api/chat、错误码 1001 明细。
"""
import json, sys, threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parent))
ASK = {"code":0,"message":"success","data":{
  "trace_id":"tr_20261008_9f3c2a","session_id":"conv_20261008_1a2b3c","message_id":"msg_20261008_5e6f70",
  "question":"公司年假有多少天？","rewritten_question":None,
  "answer":"根据《员工手册》，入职满 1 年不满 10 年的员工每年享有 5 天年假 [1]。","answer_type":"answered",
  "citations":[{"index":1,"doc_id":"doc_20261005_3f9a1c","source_file":"01_员工手册.pdf","location":"第 3 页",
                "snippet":"第三章 假期管理……","score":0.8612,"rerank_score":None,"chunk_id":"doc_20261005_3f9a1c:3"}],
  "retrieved":[{"rank":1,"chunk_id":"doc_20261005_3f9a1c:3","source_file":"01_员工手册.pdf","location":"第 3 页","score":0.8612}],
  "model":"deepseek-chat","usage":{"total_tokens":1650},"latency_ms":4200}}
HEALTH = {"code":0,"message":"success","data":{"status":"ok","version":"0.1.0","time":"2026-10-01T10:20:30+08:00",
  "dependencies":{"llm":{"status":"ok","model":"deepseek-chat"},
    "embedding":{"status":"ok","model":"BAAI/bge-small-zh-v1.5","dim":512},
    "vector_store":{"status":"ok","collection":"enterprise_kb","chunk_count":128},
    "sqlite":{"status":"ok","path":"data/app.db"}}}}
DOCS = {"code":0,"message":"success","data":{"total":1,"page":1,"page_size":20,"items":[
  {"doc_id":"doc_20261005_3f9a1c","filename":"01_员工手册.pdf","file_type":"pdf","size_bytes":196254,
   "chunk_count":42,"upload_time":"2026-10-05T14:00:00+08:00","status":"success"}]}}
UPLOAD = {"code":0,"message":"上传完成：成功 1 个，失败 1 个","data":{"total":2,"succeeded":1,"failed":1,"items":[
  {"doc_id":"doc_x","filename":"01_员工手册.pdf","file_type":"pdf","size_bytes":196254,"status":"success","chunk_count":42,"elapsed_ms":3210,"error_code":None,"error_message":None},
  {"doc_id":None,"filename":"broken.pdf","file_type":"pdf","size_bytes":10240,"status":"failed","chunk_count":0,"elapsed_ms":150,"error_code":2002,"error_message":"《broken.pdf》解析失败：文件可能已损坏或为扫描件"}]}}
BAD = {"code":1001,"message":"参数校验失败","data":{"errors":[{"field":"question","reason":"问题不能为空"}]}}
CHAT = {"code":0,"message":"success","data":{"trace_id":"tr_x","session_id":"conv_x","reply":"你好，我是企业知识库助手。",
  "model":"deepseek-chat","usage":{"total_tokens":90},"latency_ms":2310,"created_at":"2026-10-01T15:20:11+08:00"}}

last_request = {}

class H(BaseHTTPRequestHandler):
    def _send(self, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200); self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        self._send(HEALTH if "health" in self.path else DOCS)
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        last_request["path"] = self.path
        last_request["body"] = raw[:400].decode("utf-8", "ignore")
        if "ask" in self.path: self._send(ASK)
        elif "chat" in self.path: self._send(CHAT)
        elif "upload" in self.path: self._send(UPLOAD)
        else: self._send(BAD)
    def log_message(self, *a): pass

srv = HTTPServer(("127.0.0.1", 0), H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

from api_client import ApiClient, ApiError

# 控制台可能是 GBK（Windows 默认），统一按 UTF-8 输出，避免自测脚本刷屏报编码错误
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 - 某些终端不支持 reconfigure
        pass
c = ApiClient(f"http://127.0.0.1:{port}")
ok = []
def chk(name, cond, extra=""):
    ok.append(cond); print(("✅ " if cond else "❌ ") + name + ("" if cond else " -> " + str(extra)))

h = c.health()
chk("health 归一化：四项依赖", h["ok"] and h["components"] == {"llm":"ok","embedding":"ok","vector_store":"ok","sqlite":"ok"}, h)

a = c.ask("公司年假有多少天？")
chk("ask：答案文本", "5 天年假" in a["answer"], a["answer"])
chk("ask：引用折叠条字段", a["citations"][0]["source_file"] == "01_员工手册.pdf" and a["citations"][0]["location"] == "第 3 页", a["citations"])
chk("ask：三态与元信息", a["answer_type"] == "answered" and a["message_id"] and a["latency_ms"] == 4200, a)

d = c.list_documents()
chk("documents：列表字段", d["total"] == 1 and d["items"][0]["chunk_count"] == 42, d)

u = c.upload([("01_员工手册.pdf", b"x", "application/pdf")])
chk("upload：成功/失败统计", u["succeeded"] == 1 and u["failed"] == 1, u)
chk("upload：逐文件失败原因", u["items"][1]["error_message"].startswith("《broken.pdf》"), u["items"][1])

chat = c.chat("你好")
chk("chat：请求字段是 message", '"message"' in last_request.get("body",""), last_request.get("body"))
chk("chat：回复解析 reply", chat["answer"].startswith("你好"), chat)

try:
    c._request("POST", "/api/whatever")
except ApiError as e:
    chk("错误态：中文提示 + errors 明细", "问题不能为空" in " ".join(e.details) and "参数" in e.message, e)
else:
    chk("错误态：中文提示 + errors 明细", False, "未抛出")

srv.shutdown()
print("\n汇总：", sum(ok), "/", len(ok), "通过")
sys.exit(0 if all(ok) else 1)