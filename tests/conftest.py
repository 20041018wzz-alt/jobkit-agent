# -*- coding: utf-8 -*-
"""pytest 共享夹具：知识库、Mock Agent、API 客户端。全部离线。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from agent import WzzAgent  # noqa: E402
from knowledge import KnowledgeBase  # noqa: E402
from llm import MockLLM  # noqa: E402


@pytest.fixture(scope="session")
def kb() -> KnowledgeBase:
    return KnowledgeBase.load(config.KNOWLEDGE_DIR)


@pytest.fixture()
def agent(kb: KnowledgeBase) -> WzzAgent:
    return WzzAgent(kb=kb, llm=MockLLM())


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from chat_service import app

    with TestClient(app) as test_client:
        yield test_client
