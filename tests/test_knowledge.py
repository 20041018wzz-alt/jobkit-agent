# -*- coding: utf-8 -*-
"""知识库切分与检索测试。"""
from __future__ import annotations

import config
from knowledge import KnowledgeBase, parse_markdown, tokenize


def test_load_all_docs(kb: KnowledgeBase):
    assert kb.size() >= 15
    docs = {chunk.doc for chunk in kb.chunks}
    assert {"profile", "projects", "job_search"} <= docs


def test_section_ids_are_parsed(kb: KnowledgeBase):
    for expected in ("PROFILE-01", "PROFILE-06", "PROJECT-01", "PROJECT-10", "JOB-01", "JOB-05"):
        assert kb.get(expected) is not None, expected


def test_id_lookup_is_case_insensitive(kb: KnowledgeBase):
    assert kb.get("project-02") is not None


def test_tokenize_mixes_chinese_bigrams_and_ascii():
    tokens = tokenize("RAG 项目用 Chroma 向量库")
    assert "rag" in tokens
    assert "chroma" in tokens
    assert "项目" in tokens
    assert "什么" not in tokenize("他熟悉什么框架")


def test_search_hits_expected_chunk(kb: KnowledgeBase):
    hits = kb.search("RAG 项目怎么切分文档，召回率多少", top_k=4, threshold=config.RELEVANCE_THRESHOLD)
    assert hits
    assert hits[0].chunk.id == "PROJECT-02"


def test_unknown_facts_gap_entries_outrank_others(kb: KnowledgeBase):
    """没有记录的信息：缺失清单条目必须排在第一位（否则模型会拿别的条目抢答）。"""
    hits = kb.search("他拿过几次奖学金，六级多少分", top_k=4, threshold=config.RELEVANCE_THRESHOLD)
    assert hits
    assert hits[0].chunk.is_gap is True
    best_evidence = max((h.score for h in hits if not h.chunk.is_gap), default=0.0)
    assert hits[0].score >= best_evidence


def test_gap_entries_are_flagged(kb: KnowledgeBase):
    assert kb.get("PROFILE-06").is_gap is True
    assert kb.get("JOB-06").is_gap is True
    assert kb.get("PROFILE-01").is_gap is False
    assert kb.get("PROJECT-02").is_gap is False


def test_search_respects_top_k(kb: KnowledgeBase):
    hits = kb.search("项目 技术 数据", top_k=2, threshold=0.0)
    assert len(hits) <= 2


def test_by_doc_filters_domain(kb: KnowledgeBase):
    assert all(chunk.doc == "job_search" for chunk in kb.by_doc("job_search"))


def test_context_block_carries_ids(kb: KnowledgeBase):
    hits = kb.search("售后工单 性能", top_k=1, threshold=0.0)
    block = kb.context_block(hits)
    assert "[PROJECT-01]" in block


def test_add_text_appends_online_knowledge(kb: KnowledgeBase):
    fresh = KnowledgeBase(list(kb.chunks))
    added = fresh.add_text("## [PROFILE-99] 临时条目\n- 测试用：喜欢用 PowerShell", doc="manual")
    assert [c.id for c in added] == ["PROFILE-99"]
    assert fresh.get("PROFILE-99") is not None
    assert fresh.search("PowerShell 临时条目", top_k=1, threshold=0.0)[0].chunk.id == "PROFILE-99"


def test_parse_markdown_requires_section_id():
    chunks = parse_markdown("# 标题\n## 没有编号的标题\n- 内容", doc="x")
    assert chunks == []


def test_bullets_extraction(kb: KnowledgeBase):
    bullets = kb.get("PROJECT-02").bullets
    assert any("Recall@4" in b for b in bullets)
