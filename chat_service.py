# -*- coding: utf-8 -*-
"""wzz-agent 服务层：FastAPI + SSE。

接口：
- GET  /                  Web 聊天界面（流式状态 + 工具调用 + 引用展示）
- POST /api/chat          JSON 问答
- POST /chat/stream       SSE 流式（节点级状态 + token 级增量 + 最终结果）
- GET  /api/agent         Agent 元信息（模式/模型/知识条目/工具清单）
- GET  /api/tools         工具清单（Function Calling schema）
- POST /api/tools/{name}  直接调用某个工具（便于调试与演示）
- GET  /api/knowledge     知识库统计与条目号
- GET  /health            健康检查

用法：python chat_service.py  →  http://127.0.0.1:8100
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

import config
from agent import WzzAgent


class TraceIdFilter(logging.Filter):
    """给每条日志带上 trace_id，便于全链路排查。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "trace_id"):
            record.trace_id = "-"
        return True


logging.basicConfig(level=config.LOG_LEVEL,
                    format="%(asctime)s [%(levelname)s] [trace=%(trace_id)s] %(message)s")
for handler in logging.root.handlers:
    handler.addFilter(TraceIdFilter())
logger = logging.getLogger("wzz-agent")

_agent: Optional[WzzAgent] = None


def get_agent() -> WzzAgent:
    """进程内单例：知识库只加载一次。"""
    global _agent
    if _agent is None:
        _agent = WzzAgent()
        meta = _agent.metadata()
        logger.info("Agent 就绪：mode=%s model=%s chunks=%d tools=%d",
                    meta["mode"], meta["model"], meta["knowledge_chunks"], len(meta["tools"]))
    return _agent


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_agent()
    logger.info("wzz-agent 服务启动：http://127.0.0.1:%d", config.PORT)
    yield
    logger.info("wzz-agent 服务已关闭")


app = FastAPI(
    title="wzz-agent · 个人分身 Agent",
    description="基于个人知识库的分身 Agent：结构化条目检索 + Function Calling + 引用溯源 + "
                "无依据拒答。无 API Key 时自动进入 Mock 模式，全流程离线可跑。",
    version=config.AGENT_VERSION,
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = None
    history: List[dict] = Field(default_factory=list)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse({"error": "参数校验失败", "detail": exc.errors()}, status_code=422)


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    trace_id = new_trace_id()
    logger.exception("[trace=%s] 未捕获异常: %s", trace_id, exc)
    return JSONResponse({"error": "服务内部错误", "trace_id": trace_id}, status_code=500)


@app.get("/")
async def index():
    path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    return FileResponse(path)


@app.get("/health")
async def health():
    agent = get_agent()
    return {"status": "ok", "mode": agent.metadata()["mode"], "chunks": agent.kb.size()}


@app.get("/api/agent")
async def api_agent():
    return get_agent().metadata()


@app.get("/api/tools")
async def api_tools():
    return {"tools": [t.as_spec() for t in get_agent().tools.values()]}


@app.post("/api/tools/{name}")
async def api_tool(name: str, payload: dict | None = None):
    agent = get_agent()
    tool = agent.tools.get(name)
    if tool is None:
        return JSONResponse({"error": f"未知工具：{name}",
                             "available": list(agent.tools)}, status_code=404)
    try:
        result = tool.run(**(payload or {}))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"工具执行失败：{exc}"}, status_code=400)
    return result


@app.get("/api/knowledge")
async def api_knowledge(q: str = "", top_k: int = 6):
    """知识库统计；带 q 时返回检索结果（页面的知识库搜索框用）。"""
    agent = get_agent()
    payload = {
        "chunks": agent.kb.size(),
        "docs": sorted({c.doc for c in agent.kb.chunks}),
        "ids": agent.kb.ids(),
        "source": config.KNOWLEDGE_SOURCE,
        "directory": str(config.KNOWLEDGE_DIR),
        "threshold": agent.threshold,
        "entries": [{"id": c.id, "doc": c.doc, "title": c.title,
                     "chars": len(c.text), "is_gap": c.is_gap} for c in agent.kb.chunks],
    }
    if q.strip():
        hits = agent.kb.search(q, top_k=top_k, threshold=0.0)
        payload["query"] = q
        payload["hits"] = [hit.as_dict() for hit in hits]
    return payload


@app.get("/api/knowledge/{chunk_id}")
async def api_knowledge_entry(chunk_id: str):
    """单条知识条目详情（页面点击条目时用）。"""
    chunk = get_agent().kb.get(chunk_id)
    if chunk is None:
        return JSONResponse({"error": f"没有条目 {chunk_id}"}, status_code=404)
    return {"id": chunk.id, "doc": chunk.doc, "title": chunk.title, "text": chunk.text,
            "chars": len(chunk.text), "bullets": chunk.bullets, "is_gap": chunk.is_gap}


@app.post("/api/evaluate")
async def api_evaluate():
    """在线跑一次评测集：引用命中率 / 拒答准确率 / 幻觉数 / 非法引用数。"""
    from evaluate import evaluate, load_cases

    agent = get_agent()
    try:
        cases = load_cases()
    except Exception as exc:  # noqa: BLE001 - 评测集缺失时给出可读原因
        return JSONResponse({"error": f"评测集不可用：{exc}"}, status_code=400)

    stats = evaluate(agent, cases)
    return {
        "mode": agent.metadata()["mode"],
        "knowledge_chunks": agent.kb.size(),
        "knowledge_source": config.KNOWLEDGE_SOURCE,
        "eval_set": config.EVAL_SET_PATH.name,
        "total": stats["total"],
        "top_k": agent.top_k,
        "metrics": {
            "recall_hit": stats["retrieval_hit"], "recall_total": stats["retrieval_cases"],
            "citation_hit": stats["citation_hit"], "citation_total": stats["citation_cases"],
            "refusal_hit": stats["refusal_hit"], "refusal_total": stats["refusal_cases"],
            "hallucinated": stats["hallucinated"], "invalid_citations": stats["invalid_citations"],
        },
        "rows": stats["rows"],
    }


@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    trace_id = new_trace_id()
    session_id = req.session_id or f"sess-{uuid.uuid4().hex[:12]}"
    logger.info("[trace=%s] 提问 [session=%s]：%s", trace_id, session_id, req.message[:60])
    try:
        result = get_agent().answer(req.message, history=req.history[-config.MAX_HISTORY:])
    except Exception as exc:  # noqa: BLE001
        logger.exception("[trace=%s] 处理异常", trace_id)
        return JSONResponse({"error": str(exc), "trace_id": trace_id}, status_code=500)
    result.update({"session_id": session_id, "trace_id": trace_id})
    return result


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE：status（节点级）/ tool（工具调用）/ delta（token 级）/ response（校验后的最终结果）。"""
    trace_id = new_trace_id()
    session_id = req.session_id or f"sess-{uuid.uuid4().hex[:12]}"
    logger.info("[trace=%s] SSE 提问 [session=%s]：%s", trace_id, session_id, req.message[:60])

    def event_stream():
        yield _sse({"type": "session", "session_id": session_id, "trace_id": trace_id})
        for event in get_agent().stream_events(req.message, history=req.history[-config.MAX_HISTORY:]):
            if event.get("type") == "response":
                event["data"].update({"session_id": session_id, "trace_id": trace_id})
            yield _sse(event)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Trace-Id": trace_id},
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


if __name__ == "__main__":
    import uvicorn

    logger.info("启动 wzz-agent：http://127.0.0.1:%d", config.PORT)
    uvicorn.run(app, host=config.HOST, port=config.PORT)
