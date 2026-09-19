# -*- coding: utf-8 -*-
"""jobkit-agent 命令行入口。

用法：
  python cli.py --ask "他熟悉哪些 AI 框架？"
  python cli.py --ask "帮我生成 PROJECT-02 的简历条目"
  python cli.py --interview PROJECT-01 --count 6
  python cli.py --tools
  python cli.py --stats
  python cli.py --web            # 启动 Web 服务
"""
from __future__ import annotations

import argparse
import json
import sys

import config
from agent import WzzAgent
from console import enable_utf8


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobkit-agent", description="求职材料与面试演练 Agent（命令行）")
    parser.add_argument("--ask", metavar="QUESTION", help="提一个问题")
    parser.add_argument("--interview", metavar="PROJECT_ID", help="针对项目生成模拟面试题")
    parser.add_argument("--count", type=int, default=5, help="面试题数量（默认 5）")
    parser.add_argument("--tools", action="store_true", help="列出可用工具")
    parser.add_argument("--stats", action="store_true", help="输出 Agent 与知识库信息")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出完整结果")
    parser.add_argument("--web", action="store_true", help="启动 Web 服务")
    return parser


def main(argv: list[str] | None = None) -> int:
    enable_utf8()  # Windows 控制台默认不是 UTF-8，打印中文前先兜底
    args = build_parser().parse_args(argv)

    if args.web:
        import uvicorn
        from chat_service import app
        uvicorn.run(app, host=config.HOST, port=config.PORT)
        return 0

    agent = WzzAgent()

    if args.tools:
        for tool in agent.tools.values():
            print(f"- {tool.name}: {tool.description}")
        return 0

    if args.stats:
        print(json.dumps(agent.metadata(), ensure_ascii=False, indent=2))
        return 0

    if args.interview:
        result = agent.tools["mock_interview"].run(project_id=args.interview, count=args.count)
        print(result["text"])
        return 0 if result.get("ok") else 1

    if args.ask:
        result = agent.answer(args.ask)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(result["answer"])
            for call in result["tool_calls"]:
                print(f"\n[工具] {call['name']} → {'成功' if call['ok'] else '失败'}")
            print(f"\n[trace={result['trace_id']}] mode={result['mode']} "
                  f"grounded={result['grounded']} 引用={len(result['references'])} 条 "
                  f"（加 --json 看完整结果）")
        return 0

    build_parser().print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
