# -*- coding: utf-8 -*-
"""Agent 主流程测试：引用溯源、拒答、工具调用、流式事件。"""
from __future__ import annotations

import pytest

from agent import WzzAgent
from knowledge import KnowledgeBase
from llm import LLMError, MockLLM


def test_answer_carries_citations(agent: WzzAgent):
    result = agent.answer("RAG 项目怎么切分文档，召回率是多少？")
    assert result["has_knowledge"] is True
    assert result["references"], result
    assert result["references"][0]["id"] == "PROJECT-02"
    assert result["grounded"] is True
    assert result["invalid_citations"] == []


def test_answer_refuses_without_evidence(agent: WzzAgent):
    result = agent.answer("他拿过几次奖学金？")
    assert result["has_knowledge"] is False
    assert result["refused"] is True
    assert "记录里没有" in result["answer"]
    assert result["references"] == []


def test_tool_call_for_number_consistency(agent: WzzAgent):
    result = agent.answer("他简历里的数字口径有哪些冲突？")
    assert [call["name"] for call in result["tool_calls"]] == ["check_number_consistency"]
    assert "34" in result["answer"]


def test_tool_call_extracts_project_id(agent: WzzAgent):
    result = agent.answer("把 PROJECT-02 写进简历，给我条目")
    assert result["tool_calls"][0]["name"] == "draft_resume_bullet"
    assert result["tool_calls"][0]["args"] == {"project_id": "PROJECT-02"}
    assert "RAG" in result["answer"]


def test_tools_are_not_called_for_plain_questions(agent: WzzAgent):
    result = agent.answer("他熟悉哪些 AI 框架？")
    assert result["tool_calls"] == []
    assert result["references"]


def test_invalid_citations_are_stripped(agent: WzzAgent):
    text, invalid = agent._validate_citations("结论来自 [PROJECT-02] 与 [NOTEXIST-99]。")
    assert "[PROJECT-02]" in text
    assert "NOTEXIST-99" not in text
    assert invalid == ["NOTEXIST-99"]


def test_history_is_forwarded_to_model(kb: KnowledgeBase):
    captured: list = []

    class SpyLLM(MockLLM):
        def complete(self, messages):
            captured.append(messages)
            return super().complete(messages)

    agent = WzzAgent(kb=kb, llm=SpyLLM())
    agent.answer("他熟悉哪些框架？", history=[{"role": "user", "content": "上一轮问题"},
                                              {"role": "assistant", "content": "上一轮回答"}])
    contents = [m["content"] for m in captured[0]]
    assert "上一轮问题" in contents and "上一轮回答" in contents


def test_stream_events_order(agent: WzzAgent):
    events = list(agent.stream_events("RAG 项目怎么切分文档？"))
    types = [event["type"] for event in events]
    assert types[0] == "status"
    assert types[-1] == "response"
    assert "delta" in types
    assert events[-1]["data"]["references"]


def test_stream_reports_tool_calls(agent: WzzAgent):
    events = list(agent.stream_events("帮我检查简历数字口径冲突"))
    tool_events = [event for event in events if event["type"] == "tool"]
    assert tool_events and tool_events[0]["name"] == "check_number_consistency"


def test_llm_failure_degrades_gracefully(kb: KnowledgeBase):
    class BrokenLLM(MockLLM):
        def complete(self, messages):
            raise LLMError("模拟网络故障")

        def stream(self, messages):  # pragma: no cover - 仅用于触发降级
            raise LLMError("模拟网络故障")

    agent = WzzAgent(kb=kb, llm=BrokenLLM())
    result = agent.answer("他熟悉哪些框架？")
    assert "记录里没有" in result["answer"]
    assert result["tool_calls"][0]["ok"] is False


def test_repeated_tool_calls_are_bounded(kb: KnowledgeBase):
    """模型反复要求同一工具时，循环必须被 max_tool_steps 截断。"""

    class LoopingLLM(MockLLM):
        def complete(self, messages):
            return '{"action": "tool", "tool": "check_number_consistency", "args": {}}'

    agent = WzzAgent(kb=kb, llm=LoopingLLM(), max_tool_steps=2)
    result = agent.answer("随便问问")
    assert len(result["tool_calls"]) <= 2


def test_metadata_describes_agent(agent: WzzAgent):
    meta = agent.metadata()
    assert meta["name"] == "wzz-agent"
    assert meta["mode"] == "mock"
    assert meta["knowledge_chunks"] == agent.kb.size()
    assert len(meta["tools"]) == 5


def test_threshold_filters_weak_hits(kb: KnowledgeBase):
    strict = WzzAgent(kb=kb, llm=MockLLM(), threshold=1.5)
    result = strict.answer("他熟悉哪些 AI 框架？")
    assert result["retrieved"] == []
    assert result["refused"] is True
