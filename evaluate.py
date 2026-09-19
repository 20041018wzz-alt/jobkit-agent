# -*- coding: utf-8 -*-
"""离线评测：事实引用命中率 / 拒答准确率 / 幻觉率（非法引用）。

固定使用 MockLLM，保证结果可复现；配置真实 API Key 后可用
`python evaluate.py --llm` 评估真实模型的幻觉情况。

用法：python evaluate.py [--llm] [--verbose]
"""
from __future__ import annotations

import argparse
import json
import sys

import config
from agent import WzzAgent
from console import enable_utf8
from llm import MockLLM, build_llm


def load_cases(path=None):
    path = path or config.EVAL_SET_PATH
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def evaluate(agent: WzzAgent, cases, verbose: bool = False) -> dict:
    stats = {
        "total": len(cases),
        "retrieval_hit": 0, "retrieval_cases": 0,
        "citation_hit": 0, "citation_cases": 0,
        "refusal_hit": 0, "refusal_cases": 0,
        "hallucinated": 0,
        "invalid_citations": 0,
        "rows": [],
    }
    for case in cases:
        result = agent.answer(case["question"])
        retrieved_ids = {item["id"] for item in result["retrieved"]}
        ref_ids = {ref["id"] for ref in result["references"]}
        expect = set(case.get("expect_ids", []))
        refused = bool(result["refused"])

        if expect:
            stats["retrieval_cases"] += 1
            stats["citation_cases"] += 1
            if expect & retrieved_ids:
                stats["retrieval_hit"] += 1
            if expect & ref_ids:
                stats["citation_hit"] += 1
        if case.get("expect_refusal"):
            stats["refusal_cases"] += 1
            if refused:
                stats["refusal_hit"] += 1
            else:
                stats["hallucinated"] += 1
        stats["invalid_citations"] += len(result["invalid_citations"])

        stats["rows"].append({
            "id": case["id"], "question": case["question"],
            "retrieved": sorted(retrieved_ids), "cited": sorted(ref_ids),
            "refused": refused, "expect": sorted(expect),
            "expect_refusal": bool(case.get("expect_refusal")),
        })
        if verbose:
            flag = "OK " if _row_ok(case, retrieved_ids, ref_ids, refused) else "FAIL"
            print(f"[{flag}] {case['id']} {case['question']}")
            print(f"       检索={sorted(retrieved_ids)} 引用={sorted(ref_ids)} 拒答={refused} 期望={sorted(expect)}")
    return stats


def _row_ok(case, retrieved_ids, ref_ids, refused) -> bool:
    expect = set(case.get("expect_ids", []))
    if case.get("expect_refusal"):
        return refused
    return bool(expect & retrieved_ids) and bool(expect & ref_ids)


def ratio(hit: int, total: int) -> str:
    return f"{hit}/{total} = {hit / total * 100:.2f}%" if total else "未统计"


def main(argv: list[str] | None = None) -> int:
    enable_utf8()  # Windows 默认 cp1252/cp936 控制台：不改编码，打印中文会直接崩
    parser = argparse.ArgumentParser(description="jobkit-agent 离线评测")
    parser.add_argument("--llm", action="store_true", help="用真实模型评测（需配置 API Key）")
    parser.add_argument("--verbose", action="store_true", help="逐题输出")
    args = parser.parse_args(argv)

    agent = WzzAgent(llm=(build_llm() if args.llm else MockLLM()))
    cases = load_cases()
    stats = evaluate(agent, cases, verbose=args.verbose)

    print("\n=== jobkit-agent 评测报告 ===")
    print(f"模式: {'真实模型 ' + config.LLM_MODEL if args.llm else 'MockLLM（离线可复现）'}")
    print(f"知识条目: {agent.kb.size()} 条 | 评测题: {stats['total']} 题")
    print(f"检索命中率 Recall@{agent.top_k}: {ratio(stats['retrieval_hit'], stats['retrieval_cases'])}")
    print(f"引用命中率:             {ratio(stats['citation_hit'], stats['citation_cases'])}")
    print(f"拒答准确率:             {ratio(stats['refusal_hit'], stats['refusal_cases'])}")
    print(f"幻觉（无依据却作答）:   {stats['hallucinated']} 题")
    print(f"非法引用（不存在的条目号）: {stats['invalid_citations']} 次")
    return 0 if stats["hallucinated"] == 0 and stats["invalid_citations"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
