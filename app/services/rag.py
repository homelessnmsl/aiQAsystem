"""RAG 主链路编排（架构设计 4.2 / 8.2；W2-07）

检索 → 上下文拼装 → Prompt 渲染（PE 交付模板）→ DeepSeek 生成 → 引用装配（程序生成，ADR-06）
→ 消息落库（SQLite messages）。

供 API 层调用（app/api/ask.py）：

    from app.services.rag import answer_question
    result = answer_question(question="年假有多少天？", session_id=sid, trace_id=tid)
    result.answer / result.answer_type / result.citations / result.retrieved ...
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Optional

from ..core.config import BASE_DIR, settings
from ..core.errors import CODE_KB_EMPTY, CODE_LLM_NO_KEY, BizError
from ..core.logging import now_iso
from .conversation import conversation_store, new_message_id
from .llm import get_llm_client
from .repository import get_repository
from .retrieval import build_citations, build_context, knowledge_is_empty, retrieve_with_raw

logger = logging.getLogger(__name__)

#: PE 交付的 RAG 提示词（W1-15 / W2-09；文件缺失时用兜底，保证离线可运行）
SYSTEM_RAG_FILE = BASE_DIR / "prompts" / "system_rag.md"
ANSWER_TEMPLATE_FILE = BASE_DIR / "prompts" / "answer_template.md"

#: 无依据兜底话术（与 prompts/system_rag.md【固定话术】一致，FR-QA-04 / M-04）
NOT_FOUND_ANSWER = "抱歉，未在企业知识库中找到相关依据。您可以换个说法提问，或联系管理员补充相关文档。"

_FALLBACK_SYSTEM = "你是企业知识库智能问答助手，只能依据【检索片段】回答；无依据时如实说明未找到，严禁编造。"
_FALLBACK_TEMPLATE = "【历史对话】\n${history}\n\n【检索片段】\n${context}\n\n【用户问题】\n${question}"


@dataclass
class RAGResult:
    """一次 RAG 问答的完整结果（字段对齐接口文档 2.6 的 data）"""

    trace_id: str
    session_id: str
    message_id: str
    question: str
    answer: str
    answer_type: str
    citations: List[Dict[str, Any]] = field(default_factory=list)
    retrieved: List[Dict[str, Any]] = field(default_factory=list)
    model: Optional[str] = None
    usage: Optional[Dict[str, int]] = None
    latency_ms: Dict[str, int] = field(default_factory=dict)
    created_at: str = ""
    rewritten_question: Optional[str] = None


def _read_prompt(path: Path, fallback: str) -> str:
    """读取 PE 提示词文件；读不到时返回内置兜底"""
    try:
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    except OSError:
        pass
    return fallback


def render_prompt(*, history: str, context: str, question: str) -> str:
    """渲染 PE 的 answer_template（string.Template.safe_substitute，PE README §2 约定）"""
    template = Template(_read_prompt(ANSWER_TEMPLATE_FILE, _FALLBACK_TEMPLATE))
    rendered = template.safe_substitute(history=history, context=context, question=question)
    if "${" in rendered:  # PE 约定：渲染后不得残留占位符
        logger.warning("Prompt 渲染后仍有未替换占位符：%s", rendered[:80])
    return rendered


def _format_history(session_id: str, rounds: int = 3) -> str:
    """最近 N 轮历史（user/assistant 交替）；空时返回「（无）」（PE README §2）"""
    history = conversation_store.history(session_id)
    if not history:
        return "（无）"
    lines: List[str] = []
    for message in history[-rounds * 2:]:
        speaker = "用户" if message.get("role") == "user" else "助手"
        lines.append(f"{speaker}：{message.get('content', '')}")
    return "\n".join(lines)


def _strip_out_of_range_marks(answer: str, max_index: int) -> str:
    """校验答案中的 [n] 引用编号：越界编号剔除并记 WARN（接口文档 2.6 实现提示 3）"""

    def _replace(match: re.Match) -> str:
        index = int(match.group(1))
        if 1 <= index <= max_index:
            return match.group(0)
        logger.warning("答案引用编号越界并已剔除：[%s]（有效范围 1~%s）", index, max_index)
        return ""

    return re.sub(r"\[(\d+)\]", _replace, answer).strip()


def _referenced_indices(answer: str, max_index: int) -> set:
    """答案中实际引用的 [n] 集合（用于筛选 citations，架构 6.9）"""
    return {
        int(match)
        for match in re.findall(r"\[(\d+)\]", answer)
        if 1 <= int(match) <= max_index
    }


def answer_question(
    *,
    question: str,
    session_id: str,
    trace_id: str,
    top_k: Optional[int] = None,
    score_threshold: Optional[float] = None,
    use_rerank: Optional[bool] = None,
) -> RAGResult:
    """RAG 主链路：检索 → 生成（或兜底）→ 引用装配 → 落库"""
    started = time.perf_counter()

    # 0. 空库兜底：不调用 LLM（接口文档 2.6 / SM-15）
    if knowledge_is_empty():
        raise BizError(CODE_KB_EMPTY, "知识库为空，请先上传文档")

    # 1. 检索：raw = 未过滤 Top-K 明细（retrieved[]），effective = 有效候选（生成与引用）
    retrieval_started = time.perf_counter()
    raw_chunks, effective = retrieve_with_raw(
        question, top_k=top_k, score_threshold=score_threshold, use_rerank=use_rerank
    )
    retrieval_ms = int((time.perf_counter() - retrieval_started) * 1000)

    retrieved = [
        {
            "rank": chunk.rank,
            "chunk_id": chunk.chunk_id,
            "doc_id": chunk.doc_id,
            "source_file": chunk.source_file,
            "location": chunk.location,
            "snippet": chunk.content[:200],
            "score": chunk.score,
            "rerank_score": chunk.rerank_score,
        }
        for chunk in raw_chunks
    ]

    message_id = new_message_id()
    generation_ms = 0
    model: Optional[str] = None
    usage: Optional[Dict[str, int]] = None

    # 2. 分支：无有效候选 → not_found（不调用 LLM，接口文档 2.6 实现提示 4）
    if not effective:
        answer, answer_type, citations = NOT_FOUND_ANSWER, "not_found", []
    else:
        effective_citations = build_citations(effective)
        context = build_context(effective)
        prompt = render_prompt(history=_format_history(session_id), context=context, question=question)
        system_prompt = _read_prompt(SYSTEM_RAG_FILE, _FALLBACK_SYSTEM)

        if not settings.llm_configured:
            raise BizError(CODE_LLM_NO_KEY, "服务未配置模型密钥，请联系管理员")

        generation_started = time.perf_counter()
        llm_result = get_llm_client().chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ])
        generation_ms = int((time.perf_counter() - generation_started) * 1000)

        answer = _strip_out_of_range_marks(llm_result.content, len(effective))
        referenced = _referenced_indices(answer, len(effective))
        if not referenced:
            # 架构 6.9：模型未使用任何编号但返回了实质答案 → 视为"无依据回答"，降级 not_found（宁可不答，不可编造）
            logger.warning("模型未使用引用编号，按架构 6.9 降级为 not_found：trace=%s", trace_id)
            answer, answer_type, citations = NOT_FOUND_ANSWER, "not_found", []
        else:
            # citations 只保留模型实际引用的 [n]（架构 6.9：依据实际引用生成，防伪造来源）
            citations = [item for item in effective_citations if item["index"] in referenced]
            answer_type = "answered"  # clarify（澄清）第3周实现（接口文档 2.6 实现提示 1）
            model = llm_result.model
            usage = vars(llm_result.usage)
            if len(answer) > settings.ANSWER_MAX_CHARS + 50:
                logger.warning("答案长度 %d 字，超过目标 %d 字（PE 评测关注）", len(answer), settings.ANSWER_MAX_CHARS)

    latency = {
        "total": int((time.perf_counter() - started) * 1000),
        "retrieval": retrieval_ms,
        "rerank": 0,  # 当前 retrieval 已含重排耗时；第3周启用重排后拆分计时
        "generation": generation_ms,
    }
    created_at = now_iso()

    # 3. 落库（SQLite messages）+ 内存上下文（第3周多轮追问复用）
    repository = get_repository()
    repository.ensure_conversation(session_id, title=question[:20])
    repository.add_message(
        message_id=new_message_id(),
        session_id=session_id,
        role="user",
        content=question,
        trace_id=trace_id,
        created_at=created_at,
    )
    repository.add_message(
        message_id=message_id,
        session_id=session_id,
        role="assistant",
        content=answer,
        citations=json.dumps(citations, ensure_ascii=False),
        trace_id=trace_id,
        latency_ms=latency["total"],
        created_at=created_at,
    )
    conversation_store.append(session_id, "user", question)
    conversation_store.append(session_id, "assistant", answer)

    logger.info(
        "问答完成：trace=%s type=%s 总耗时 %dms（检索 %d / 生成 %d）",
        trace_id, answer_type, latency["total"], retrieval_ms, generation_ms,
    )
    return RAGResult(
        trace_id=trace_id,
        session_id=session_id,
        message_id=message_id,
        question=question,
        answer=answer,
        answer_type=answer_type,
        citations=citations,
        retrieved=retrieved,
        model=model,
        usage=usage,
        latency_ms=latency,
        created_at=created_at,
    )
