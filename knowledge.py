# -*- coding: utf-8 -*-
"""个人知识库：分域切分 + 纯 Python TF-IDF 检索。

设计取舍：
- 知识是按 `## [ID] 标题` 组织的结构化条目，切分粒度 = 检索粒度，
  引用时可以精确溯源到条目号（如 `[PROJECT-01]`）。
- 检索用中文二元组 + 英文词 + TF-IDF 余弦，**不依赖任何第三方库**，
  离线可复现；生产可整体替换为向量检索（接口保持不变）。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

SECTION_RE = re.compile(r"^##\s*\[(?P<id>[A-Za-z]+-\d+)\]\s*(?P<title>.+?)\s*$")
ASCII_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_+#.\-]*")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# 高频无信息二元组（查询里的疑问词/代词），避免"他""项目"之类把无关条目拉上来
# 疑问词/指代词/套话：不是内容词，参与打分只会把无关条目拉上来
STOPWORDS = {
    "什么", "怎么", "怎样", "如何", "哪些", "哪个", "哪家", "哪里", "哪儿", "多少", "哪一",
    "几次", "几个", "几家", "几年", "何时", "为何", "为什么", "是否", "有无", "有没",
    "一下", "这个", "那个", "我们", "你们", "他们", "他的", "她的", "他是", "她是", "是谁",
    "告诉", "介绍", "讲讲", "说说", "请问", "帮我", "做过", "做了", "是不", "吗？", "呢？",
}

# BM25 参数：k1 控制词频饱和，b 控制文档长度归一（0=不归一，1=完全归一）
BM25_K1 = 1.2
BM25_B = 0.75
# 标题命中等价于额外出现 3 次该词
TITLE_WEIGHT = 3.0


def tokenize(text: str) -> List[str]:
    """中文二元组 + 英文/数字词，小写归一。"""
    lowered = text.lower()
    tokens = [m.group(0) for m in ASCII_RE.finditer(lowered)]
    cjk = CJK_RE.findall(lowered)
    if len(cjk) == 1:
        tokens.append(cjk[0])
    for i in range(len(cjk) - 1):
        tokens.append(cjk[i] + cjk[i + 1])
    return [t for t in tokens if t not in STOPWORDS]


@dataclass
class Chunk:
    """一个知识条目。"""

    id: str
    doc: str          # 所属知识域（profile / projects / job_search）
    title: str
    text: str
    tokens: List[str] = field(default_factory=list)
    term_freq: Dict[str, float] = field(default_factory=dict)
    length: int = 0
    title_terms: set = field(default_factory=set)

    @property
    def bullets(self) -> List[str]:
        """条目里的要点行（`- ` / `1. ` 开头），用于生成简历条目与回答。"""
        out = []
        for line in self.text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("- ", "* ")) or re.match(r"^\d+[.、)]\s*", stripped):
                out.append(re.sub(r"^(\d+[.、)]|[-*])\s*", "", stripped))
        return out

    @property
    def is_gap(self) -> bool:
        """是否为"缺失清单"条目（记录里明确没有的信息）。

        这类条目只在检索时说明"哪些信息没记录"，**不能当作事实依据**，
        否则"他拿过几次奖学金"会因为命中"待补齐项"而被当成有依据作答。
        """
        return self.title.startswith(("未记录", "待补齐"))

    def as_dict(self) -> dict:
        return {"id": self.id, "doc": self.doc, "title": self.title, "text": self.text,
                "is_gap": self.is_gap}

    def summary(self, limit: int = 400) -> str:
        text = " ".join(self.text.split())
        return text if len(text) <= limit else text[:limit] + "…"


@dataclass
class Hit:
    """一条检索结果。score 是主排序分（IDF 覆盖率），tie 是同分时的次排序分（BM25）。"""

    chunk: Chunk
    score: float
    tie: float = 0.0

    def as_dict(self) -> dict:
        return {"id": self.chunk.id, "doc": self.chunk.doc, "title": self.chunk.title,
                "score": round(self.score, 4), "is_gap": self.chunk.is_gap}


def parse_markdown(text: str, doc: str) -> List[Chunk]:
    """把知识文档切成 `## [ID] 标题` 条目。"""
    chunks: List[Chunk] = []
    current_id: Optional[str] = None
    current_title = ""
    buffer: List[str] = []

    def flush() -> None:
        if current_id is None:
            return
        body = "\n".join(buffer).strip()
        if body:
            chunks.append(Chunk(id=current_id, doc=doc, title=current_title, text=body))

    for line in text.splitlines():
        match = SECTION_RE.match(line)
        if match:
            flush()
            current_id = match.group("id")
            current_title = match.group("title")
            buffer = []
            continue
        if current_id is not None:
            buffer.append(line)
    flush()
    return chunks


class KnowledgeBase:
    """分域知识库，支持结构化检索与在线追加。"""

    def __init__(self, chunks: Sequence[Chunk] = ()) -> None:
        self.chunks: List[Chunk] = list(chunks)
        self._by_id: Dict[str, Chunk] = {}
        self._idf: Dict[str, float] = {}
        self._rebuild()

    # ── 构建 ────────────────────────────────────────────────────────────────
    @classmethod
    def load(cls, directory: Path | str) -> "KnowledgeBase":
        """从目录加载全部 `*.md` 知识文档（文件名即知识域）。"""
        directory = Path(directory)
        chunks: List[Chunk] = []
        for path in sorted(directory.glob("*.md")):
            chunks.extend(parse_markdown(path.read_text(encoding="utf-8"), path.stem))
        return cls(chunks)

    def add_text(self, text: str, doc: str = "manual") -> List[Chunk]:
        """在线追加知识（同样按条目切分），返回新增条目。"""
        added = parse_markdown(text, doc)
        self.chunks.extend(added)
        self._rebuild()
        return added

    def _rebuild(self) -> None:
        self._by_id = {c.id: c for c in self.chunks}
        total = len(self.chunks) or 1
        df: Dict[str, int] = {}
        for chunk in self.chunks:
            chunk.tokens = tokenize(f"{chunk.title} {chunk.text}")
            chunk.term_freq = {}
            for term in chunk.tokens:
                chunk.term_freq[term] = chunk.term_freq.get(term, 0.0) + 1.0
            chunk.length = len(chunk.tokens) or 1
            chunk.title_terms = set(tokenize(chunk.title))
            for term in set(chunk.tokens):
                df[term] = df.get(term, 0) + 1
        self._idf = {term: math.log((total + 1) / (count + 1)) + 1.0 for term, count in df.items()}
        self._avg_length = (sum(c.length for c in self.chunks) / total) if self.chunks else 1.0

    # ── 查询 ────────────────────────────────────────────────────────────────
    def search(self, query: str, top_k: int = 4, threshold: float = 0.0) -> List[Hit]:
        """检索：**IDF 加权的查询词覆盖率**为主分，BM25 为次分。

        为什么不用 BM25 当主分：BM25 偏向"短且重复命中某个词"的条目，
        结果是一张提到 "RAG" 的项目表格会排在真正讲 RAG 切分的项目前面。
        覆盖率回答的是"这条目覆盖了问题里多少（按 IDF 加权的）词"，
        更贴合本项目的场景——事实型问答要的是**答得上**，而不是词频高。

        - 主分 score = Σ IDF(命中词) / Σ IDF(查询词) ∈ [0, 1+]，标题命中另加 15% 权重
        - 次分 tie   = BM25 / Σ IDF(查询词)：词频饱和（k1）与文档长度归一（b），仅用于同分排序
        - 阈值作用在主分上：覆盖率过低说明"知识库里没有讲这件事"
        """
        query_terms = {t: self._idf[t] for t in tokenize(query) if t in self._idf}
        if not query_terms:
            return []
        idf_sum = sum(query_terms.values()) or 1.0

        hits: List[Hit] = []
        for chunk in self.chunks:
            matched = [t for t in query_terms
                       if chunk.term_freq.get(t, 0.0) > 0 or t in chunk.title_terms]
            if not matched:
                continue
            coverage = sum(query_terms[t] for t in matched) / idf_sum
            title_bonus = 0.15 * sum(query_terms[t] for t in matched
                                     if t in chunk.title_terms) / idf_sum
            score = coverage + title_bonus
            if score <= threshold:
                continue
            hits.append(Hit(chunk=chunk, score=score, tie=self._bm25(chunk, query_terms, idf_sum)))
        hits.sort(key=lambda h: (-h.score, -h.tie, h.chunk.id))
        return hits[:top_k]

    def _bm25(self, chunk: Chunk, query_terms: Dict[str, float], idf_sum: float) -> float:
        """BM25 分数（除以查询 IDF 之和）：词频饱和 + 文档长度归一，用作同分次排序。"""
        raw = 0.0
        for term, weight in query_terms.items():
            tf = chunk.term_freq.get(term, 0.0)
            if term in chunk.title_terms:
                tf += TITLE_WEIGHT
            if tf <= 0:
                continue
            denominator = tf + BM25_K1 * (1 - BM25_B + BM25_B * chunk.length / self._avg_length)
            raw += weight * (tf * (BM25_K1 + 1)) / denominator
        return raw / idf_sum

    # ── 访问 ────────────────────────────────────────────────────────────────
    def get(self, chunk_id: str) -> Optional[Chunk]:
        return self._by_id.get(chunk_id.upper())

    def by_doc(self, doc: str) -> List[Chunk]:
        return [c for c in self.chunks if c.doc == doc]

    def ids(self) -> List[str]:
        return [c.id for c in self.chunks]

    def query_terms(self, query: str) -> List[str]:
        """查询里被知识库收录的词（未收录的词不参与打分）。"""
        return [t for t in tokenize(query) if t in self._idf]

    def matched_terms(self, chunk: Chunk, query: str) -> List[str]:
        """某条目命中了查询里的哪些词（含标题命中）。"""
        return [t for t in set(self.query_terms(query))
                if chunk.term_freq.get(t, 0.0) > 0 or t in chunk.title_terms]

    def absence_terms(self) -> set:
        """缺失词表：从"缺失清单"条目里解析出的**没有记录的主题词**。

        用途：只靠这些词命中的普通条目不算证据（例如某条目写了"校招/实习均可投递"，
        不代表它记录了实习经历）。缺失词表由知识库自身推导，不需要人工维护。
        """
        terms: set = set()
        for chunk in self.chunks:
            if not chunk.is_gap:
                continue
            for line in chunk.text.splitlines():
                cleaned = line.strip().lstrip("-*# ").strip()
                if not cleaned:
                    continue
                cleaned = re.sub(r"^[^：:]{0,12}[：:]", "", cleaned)     # 去掉"未记录类："之类的前缀
                for item in re.split(r"[、,，;；/]", cleaned):
                    item = item.strip()
                    if 1 < len(item) <= 20:
                        terms.update(tokenize(item))
        return terms

    def size(self) -> int:
        return len(self.chunks)

    def context_block(self, hits: Iterable[Hit], max_chars: int = 2400) -> str:
        """把检索结果拼成给 LLM 的上下文块（带条目号，便于引用溯源）。"""
        parts: List[str] = []
        used = 0
        for hit in hits:
            piece = f"[{hit.chunk.id}] {hit.chunk.title}\n{hit.chunk.text.strip()}"
            if used + len(piece) > max_chars:
                break
            parts.append(piece)
            used += len(piece)
        return "\n\n".join(parts)
