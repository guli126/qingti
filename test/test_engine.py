"""对话编排的测试：模型跑偏时能不能自动补救。

不开窗口，起一个假 AI 就行，秒出结果。

用法：python test/test_engine.py
"""

import os
import sys
import threading
import time
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "test"))

from _sandbox import isolate  # noqa: E402

isolate()

import mock_ai  # noqa: E402
from core import engine, paths, templates  # noqa: E402

paths.seed_prompts()
templates.ensure_defaults()

PORT = 8903
FAIL = []
LOG = []


def check(name, ok, extra=""):
    LOG.append(("PASS" if ok else "FAIL") + " · " + name + (("  " + extra) if extra else ""))
    if not ok:
        FAIL.append(name)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), mock_ai.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.3)

    conn = {"base_url": "http://127.0.0.1:%d/v1" % PORT, "api_key": "sk-mock",
            "model": "mock", "protocol": "openai", "timeout": 30, "stream": True}
    system = "测试用系统提示词"

    # 正常情况：一问就回选项
    parsed, _ = engine.send(conn, system, [{"role": "user", "content": "做个记账工具"}])
    check("正常回复解析成选项", parsed["kind"] == "ask" and len(parsed["ask"]) == 2,
          "%s %d" % (parsed["kind"], len(parsed["ask"])))

    # 跑偏：第一次回大白话，自动催一次后应该拿到选项
    parsed, result = engine.send(
        conn, system, [{"role": "user", "content": "跑偏测试：做个记账工具"}])
    check("模型跑偏时自动补救成功", parsed["kind"] == "ask",
          parsed["kind"])
    check("补救后拿到的题数为 2", len(parsed["ask"]) == 2, str(len(parsed["ask"])))
    check("补救后不是那句大白话",
          "我先问你几个问题" not in (parsed.get("raw") or "")[:20],
          (parsed.get("raw") or "")[:20])

    # 关掉补救时，跑偏就还是跑偏（说明这个开关是真的在管用）
    parsed, _ = engine.send(
        conn, system, [{"role": "user", "content": "跑偏测试2"}], retry=False)
    check("retry=False 时不做补救", parsed["kind"] == "text", parsed["kind"])

    # 最后一轮还在提问：必须强制催出结果，不能让用户干等
    parsed, _ = engine.send(
        conn, system, [{"role": "user", "content": "赖着提问"}],
        round_=3, max_rounds=3)
    check("末轮还在提问会被强制出结果", parsed["kind"] == "prompt",
          parsed["kind"])
    check("强制出来的结果有正文", len(parsed.get("prompt") or "") > 100,
          str(len(parsed.get("prompt") or "")))

    # 非末轮时不该多花一次请求去强制
    parsed, _ = engine.send(
        conn, system, [{"role": "user", "content": "赖着提问"}],
        round_=1, max_rounds=3)
    check("非末轮不会强制出结果", parsed["kind"] == "ask", parsed["kind"])

    srv.shutdown()

    print("\n".join(LOG))
    print("---")
    print("全部通过" if not FAIL else "失败 %d 项：%s" % (len(FAIL), FAIL))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
