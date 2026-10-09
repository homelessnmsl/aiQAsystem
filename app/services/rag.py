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
from typing import Any, Dict, Iterator, List, Optional

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

#: 多轮改写系统提示（架构 8.2 ①；FR-QA-05：理解"那转正后呢？"这类省略式追问）
REWRITE_SYSTEM_PROMPT = (
    "你是检索查询改写助手。结合对话历史，把用户当前问题改写为不依赖上下文、语义完整、可独立检索的中文问句。"
    "若当前问题本身已语义完整（不依赖历史），原样输出。只输出改写后的问句，一行，不要任何解释。"
)


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


@dataclass
class StreamPrep:
    """流式问答的准备阶段结果（检索已完成，等待逐块生成，接口文档 2.11）"""

    trace_id: str
    session_id: str
    message_id: str
    question: str
    rewritten_question: Optional[str]
    history_entries: List[Dict[str, str]]
    retrieved: List[Dict[str, Any]]
    citations: List[Dict[str, Any]]  # retrieval 事件携带：全部有效候选，编号 1..N 连续
    effective: List[Any]             # List[RetrievedChunk]，生成与落库用
    latency: Dict[str, int]          # total / retrieval / rerank / generation
    started: float


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


def _history_entries(session_id: str) -> List[Dict[str, str]]:
    """会话历史：优先内存；内存为空时从 SQLite 恢复（服务器重启后仍可续聊，FR-CONV-01）"""
    entries = conversation_store.history(session_id)
    if entries:
        return entries
    try:
        rows = get_repository().list_messages(session_id)
    except Exception as exc:  # noqa: BLE001 - 历史缺失不应阻塞问答
        logger.warning("会话历史恢复失败（按无历史处理）：%s", exc)
        return []
    return [{"role": row["role"], "content": row["content"]} for row in rows]


def _format_history(entries: List[Dict[str, str]], rounds: int = 3) -> str:
    """最近 N 轮历史（user/assistant 交替）；空时返回「（无）」（PE README §2）"""
    if not entries:
        return "（无）"
    lines: List[str] = []
    for message in entries[-rounds * 2:]:
        speaker = "用户" if message.get("role") == "user" else "助手"
        lines.append(f"{speaker}：{message.get('content', '')}")
    return "\n".join(lines)


def _rewrite_question(question: str, history_entries: List[Dict[str, str]]) -> Optional[str]:
    """多轮改写：把省略式追问补全为可独立检索的问题（架构 8.2 ①、FR-QA-05）

    - 无历史 → 不改写（返回 None）；
    - 改写失败（LLM 异常等）→ 降级为原文检索，不影响主链路（异常兜底）；
    - 改写结果与原文相同 → 视为未改写（接口文档 2.6：未改写为 null）。
    """
    if not history_entries:
        return None

    history_text = _format_history(history_entries, rounds=3)
    user_prompt = f"【对话历史】\n{history_text}\n\n【当前问题】\n{question}\n\n【改写结果】"
    try:
        result = get_llm_client().chat(
            [
                {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
        )
    except BizError as exc:
        logger.warning("多轮改写失败（降级为原文检索）：%s", exc)
        return None

    rewritten = result.content.strip().strip("“”\"'").strip()
    if not rewritten or rewritten == question.strip():
        return None
    if len(rewritten) > 500:
        rewritten = rewritten[:500]
    logger.info("多轮改写：%r → %r", question, rewritten)
    return rewritten


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


def _renumber_citations(answer: str, referenced: set) -> tuple:
    """对外引用编号连续化（D2-02 方案B，2026-10-09 定稿）

    模型看到的上下文编号为 1..N（连续），但答案可能只引用其中部分（如 [1][3]）。
    对外返回时按答案中首次出现的顺序重排为连续 [1][2]…，citations 的 index 同步重排；
    溯源字段（doc_id/source_file/location/snippet/chunk_id）保持不变。
    """
    order: list = []
    for match in re.finditer(r"\[(\d+)\]", answer):
        index = int(match.group(1))
        if index in referenced and index not in order:
            order.append(index)
    mapping = {old: new for new, old in enumerate(order, start=1)}

    def _replace(match: re.Match) -> str:
        index = int(match.group(1))
        return f"[{mapping.get(index, index)}]"

    return re.sub(r"\[(\d+)\]", _replace, answer), mapping


def _persist_qa(
    *,
    session_id: str,
    trace_id: str,
    message_id: str,
    question: str,
    answer: str,
    citations: List[Dict[str, Any]],
    latency_ms: int,
) -> str:
    """落库（SQLite messages + 会话行）+ 内存上下文；同步 / 流式路径共用，返回 created_at"""
    created_at = now_iso()
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
        latency_ms=latency_ms,
        created_at=created_at,
    )
    conversation_store.append(session_id, "user", question)
    conversation_store.append(session_id, "assistant", answer)
    return created_at


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

    # 0.5 会话历史（优先内存；服务器重启后从 SQLite 恢复）
    history_entries = _history_entries(session_id)

    # 1. 多轮改写（架构 8.2 ①）→ 检索：raw = 未过滤 Top-K 明细（retrieved[]）、effective = 有效候选
    retrieval_started = time.perf_counter()
    rewritten_question = _rewrite_question(question, history_entries)
    search_question = rewritten_question or question
    raw_chunks, effective = retrieve_with_raw(
        search_question, top_k=top_k, score_threshold=score_threshold, use_rerank=use_rerank
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
        prompt = render_prompt(history=_format_history(history_entries), context=context, question=question)
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
            # D2-02 方案B：对外引用编号连续化（按答案中首次出现顺序重排 [1][2]…）
            answer, citation_map = _renumber_citations(answer, referenced)
            # citations 只保留模型实际引用的片段，index 同步为连续编号（架构 6.9：依据实际引用生成，防伪造来源）
            citations = [
                {**item, "index": citation_map[item["index"]]}
                for item in effective_citations
                if item["index"] in referenced
            ]
            citations.sort(key=lambda item: item["index"])
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
    # 3. 落库（SQLite messages）+ 内存上下文（同步 / 流式共用）
    created_at = _persist_qa(
        session_id=session_id,
        trace_id=trace_id,
        message_id=message_id,
        question=question,
        answer=answer,
        citations=citations,
        latency_ms=latency["total"],
    )

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
        rewritten_question=rewritten_question,
    )


# ============================================================
# 流式问答（接口文档 2.11；W3-07）
# ============================================================
def prepare_stream(
    *,
    question: str,
    session_id: str,
    trace_id: str,
    top_k: Optional[int] = None,
    score_threshold: Optional[float] = None,
    use_rerank: Optional[bool] = None,
) -> StreamPrep:
    """流式准备阶段：空库校验 → 多轮改写 → 检索（同步执行，失败按 1.4 统一 JSON 错误返回）

    准备阶段完成后才开始下发 SSE 事件；此阶段抛出 BizError 由 API 层按统一响应处理。
    """
    started = time.perf_counter()

    if knowledge_is_empty():
        raise BizError(CODE_KB_EMPTY, "知识库为空，请先上传文档")

    history_entries = _history_entries(session_id)
    retrieval_started = time.perf_counter()
    rewritten_question = _rewrite_question(question, history_entries)
    search_question = rewritten_question or question
    raw_chunks, effective = retrieve_with_raw(
        search_question, top_k=top_k, score_threshold=score_threshold, use_rerank=use_rerank
    )
    retrieval_ms = int((time.perf_counter() - retrieval_started) * 1000)

    if effective and not settings.llm_configured:
        raise BizError(CODE_LLM_NO_KEY, "服务未配置模型密钥，请联系管理员")

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
    return StreamPrep(
        trace_id=trace_id,
        session_id=session_id,
        message_id=new_message_id(),
        question=question,
        rewritten_question=rewritten_question,
        history_entries=history_entries,
        retrieved=retrieved,
        citations=build_citations(effective),
        effective=effective,
        latency={
            "total": int((time.perf_counter() - started) * 1000),
            "retrieval": retrieval_ms,
            "rerank": 0,
            "generation": 0,
        },
        started=started,
    )


def stream_events(prep: StreamPrep) -> Iterator[Dict[str, Any]]:
    """生成 SSE 事件流（接口文档 2.11）：retrieval → delta* → done；异常时以 error 收尾

    - retrieval 事件先发（前端可先渲染引用卡片；citations 为全部有效候选，编号 1..N 连续）；
    - 无有效候选 → 单条 delta（固定兜底话术）+ done（不调用 LLM，usage=null）；
    - 生成中异常 → error 事件收尾（不落库；done / error 必为最后一个事件）；
    - 流式路径无法事后重排/降级（已下发内容不可回撤）：落库内容与下发一致，
      越界/未引用编号仅记日志（质量护栏，PE 评测关注）；同步路径保持 6.9 / D2-02 语义。
    """
    yield {
        "type": "retrieval",
        "trace_id": prep.trace_id,
        "session_id": prep.session_id,
        "message_id": prep.message_id,
        "retrieved": prep.retrieved,
        "citations": prep.citations,
    }

    # 无有效候选：不调用 LLM（接口文档 2.6 实现提示 4）
    if not prep.effective:
        answer = NOT_FOUND_ANSWER
        yield {"type": "delta", "content": answer}
        prep.latency["total"] = int((time.perf_counter() - prep.started) * 1000)
        _persist_qa(
            session_id=prep.session_id,
            trace_id=prep.trace_id,
            message_id=prep.message_id,
            question=prep.question,
            answer=answer,
            citations=[],
            latency_ms=prep.latency["total"],
        )
        yield {"type": "done", "usage": None, "latency_ms": prep.latency}
        return

    context = build_context(prep.effective)
    prompt = render_prompt(
        history=_format_history(prep.history_entries),
        context=context,
        question=prep.question,
    )
    system_prompt = _read_prompt(SYSTEM_RAG_FILE, _FALLBACK_SYSTEM)

    generation_started = time.perf_counter()
    parts: List[str] = []
    try:
        for chunk in get_llm_client().stream_chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]
        ):
            parts.append(chunk)
            yield {"type": "delta", "content": chunk}
    except BizError as exc:
        # 生成中失败：不落库、不发 done（error 必为最后一个事件）
        logger.warning("流式生成失败：trace=%s code=%s %s", prep.trace_id, exc.code, exc.message)
        yield {"type": "error", "code": exc.code, "message": exc.message}
        return

    answer = "".join(parts).strip()
    prep.latency["generation"] = int((time.perf_counter() - generation_started) * 1000)
    prep.latency["total"] = int((time.perf_counter() - prep.started) * 1000)

    # 质量护栏（仅日志；流式路径不做事后重排/降级，见函数注释）
    referenced = _referenced_indices(answer, len(prep.effective))
    if not referenced:
        logger.warning("流式答案未使用引用编号（架构 6.9 质量关注）：trace=%s", prep.trace_id)
    elif len(referenced) < len(prep.effective):
        logger.info(
            "流式答案引用 %d/%d 个片段（retrieval 事件下发全集，编号一一对应）：trace=%s",
            len(referenced), len(prep.effective), prep.trace_id,
        )

    _persist_qa(
        session_id=prep.session_id,
        trace_id=prep.trace_id,
        message_id=prep.message_id,
        question=prep.question,
        answer=answer,
        citations=prep.citations,
        latency_ms=prep.latency["total"],
    )
    # 注：usage 暂为 null（当前流式响应不含用量字段；后续 SDK 支持后可补齐）
    yield {"type": "done", "usage": None, "latency_ms": prep.latency}
