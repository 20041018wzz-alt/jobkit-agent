# -*- coding: utf-8 -*-
"""HTTP 接口测试（FastAPI TestClient，全部离线）。"""
from __future__ import annotations


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["chunks"] > 0


def test_agent_metadata(client):
    body = client.get("/api/agent").json()
    assert body["name"] == "jobkit-agent"
    assert len(body["tools"]) == 5
    assert body["knowledge_chunks"] > 0


def test_chat_returns_answer_and_references(client):
    resp = client.post("/api/chat", json={"message": "RAG 项目怎么切分文档？"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["references"]
    assert body["trace_id"]
    assert body["session_id"].startswith("sess-")


def test_chat_rejects_empty_message(client):
    resp = client.post("/api/chat", json={"message": ""})
    assert resp.status_code == 422
    assert resp.json()["error"] == "参数校验失败"


def test_chat_stream_emits_sse_events(client):
    with client.stream("POST", "/chat/stream", json={"message": "他熟悉哪些 AI 框架？"}) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        payload = "".join(resp.iter_text())
    assert '"type": "status"' in payload
    assert '"type": "delta"' in payload
    assert '"type": "response"' in payload
    assert "[DONE]" in payload


def test_tools_listing_and_direct_call(client):
    tools = client.get("/api/tools").json()["tools"]
    assert {tool["name"] for tool in tools} == {
        "query_knowledge", "draft_resume_bullet", "check_number_consistency",
        "mock_interview", "summarize_profile"}

    resp = client.post("/api/tools/mock_interview", json={"project_id": "PROJECT-01", "count": 3})
    assert resp.status_code == 200
    assert len(resp.json()["data"]["questions"]) == 3


def test_unknown_tool_returns_404(client):
    resp = client.post("/api/tools/not_a_tool", json={})
    assert resp.status_code == 404


def test_knowledge_listing(client):
    body = client.get("/api/knowledge").json()
    assert body["chunks"] > 0
    assert "PROJECT-02" in body["ids"]
    assert {"profile", "projects", "job_search"} <= set(body["docs"])


def test_index_page_served(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "jobkit-agent" in resp.text
    # 页面必备的三个面板与 SSE 消费逻辑
    assert "知识库" in resp.text and "工具台" in resp.text and "/chat/stream" in resp.text


def test_knowledge_search_endpoint(client):
    body = client.get("/api/knowledge", params={"q": "RAG 项目怎么切分文档"}).json()
    assert body["hits"]
    assert body["hits"][0]["id"].startswith(("PROJECT", "PROFILE", "JOB"))
    assert body["query"] == "RAG 项目怎么切分文档"
    assert body["chunks"] > 0


def test_knowledge_entry_detail_endpoint(client):
    body = client.get("/api/knowledge/PROJECT-02").json()
    assert body["title"]
    assert body["text"]
    assert body["chars"] > 0
    assert client.get("/api/knowledge/NOT-EXIST").status_code == 404


def test_evaluate_endpoint(client):
    body = client.post("/api/evaluate").json()
    assert body["total"] >= 10
    assert len(body["rows"]) == body["total"]
    assert body["metrics"]["hallucinated"] == 0
    assert body["metrics"]["invalid_citations"] == 0
    assert body["metrics"]["refusal_hit"] == body["metrics"]["refusal_total"]
