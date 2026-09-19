# -*- coding: utf-8 -*-
"""Function Calling 工具测试。"""
from __future__ import annotations

from knowledge import KnowledgeBase
from tools import build_tools


def test_registry_exposes_five_tools(kb: KnowledgeBase):
    tools = build_tools(kb)
    assert set(tools) == {"query_knowledge", "draft_resume_bullet", "check_number_consistency",
                          "mock_interview", "summarize_profile"}
    for tool in tools.values():
        spec = tool.as_spec()
        assert spec["name"] and spec["description"]
        assert spec["parameters"]["type"] == "object"


def test_draft_resume_bullet_keeps_quantified_bullets(kb: KnowledgeBase):
    result = build_tools(kb)["draft_resume_bullet"].run(project_id="PROJECT-02")
    assert result["ok"] is True
    assert "文档检索" in result["data"]["header"]
    assert result["data"]["bullets"]
    assert any(any(ch.isdigit() for ch in bullet) for bullet in result["data"]["bullets"])


def test_draft_resume_bullet_unknown_project(kb: KnowledgeBase):
    result = build_tools(kb)["draft_resume_bullet"].run(project_id="PROJECT-404")
    assert result["ok"] is False
    assert "PROJECT-01" in result["text"]


def test_check_number_consistency_finds_conflicts(kb: KnowledgeBase):
    result = build_tools(kb)["check_number_consistency"].run()
    items = {c["item"] for c in result["data"]["conflicts"]}
    assert any("pytest" in item for item in items)
    assert "34" in result["text"]


def test_mock_interview_returns_requested_count(kb: KnowledgeBase):
    result = build_tools(kb)["mock_interview"].run(project_id="PROJECT-01", count=6)
    assert result["ok"] is True
    assert len(result["data"]["questions"]) == 6
    assert any("Supervisor" in q or "意图" in q for q in result["data"]["questions"])


def test_summarize_profile_contains_school(kb: KnowledgeBase):
    result = build_tools(kb)["summarize_profile"].run()
    assert result["ok"] is True
    # 学校名从知识库本身读取，测试对"示例知识库 / 私有知识库"都成立
    school_line = next(line for line in kb.get("PROFILE-01").text.splitlines()
                       if line.strip().startswith("- 学校"))
    assert result["data"]["school"] in school_line
    assert "PROFILE-01" in result["text"]


def test_query_knowledge_reports_misses(kb: KnowledgeBase):
    """关键词检索：命中给出条目号，完全没有相关词时明确报告没有。"""
    tools = build_tools(kb)
    hit = tools["query_knowledge"].run(keyword="RAG", top_k=2)
    assert hit["ok"] is True and hit["data"]["hits"]
    miss = tools["query_knowledge"].run(keyword="红点奖")
    assert miss["ok"] is False
    assert "没有" in miss["text"]
