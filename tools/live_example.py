# -*- coding: utf-8 -*-
"""跑一次真实会话，把过程完整记录下来（用于文档里的「运行实例」）。

用法：python tools/live_example.py
产出：video/实例-编程记账.md
"""

import io
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import engine, llm, store  # noqa: E402

SCENE, MODE = "coding", "task"
INPUT = "我想做个能记账的东西，每个月花了多少钱能看明白"
ANSWER = "我自己用；每月一张汇总表；能导出 Excel"


def main():
    cfg = store.load_config()
    conn = engine.active_connection(cfg)
    if not conn:
        print("没有可用配置")
        return 1
    tid = engine.template_id(SCENE, MODE)
    msgs = [{"role": "user", "content": INPUT}]
    out = []
    out.append("# 运行实例 · 编程 / 任务提示词\n")
    out.append("- 模型：`%s`" % conn.get("model"))
    out.append("- 场景 / 模式：编程 · 任务提示词（模板 `%s`）" % tid)
    out.append("- 时间：%s\n" % time.strftime("%Y-%m-%d %H:%M"))
    out.append("## ① 用户只说了这么一句\n")
    out.append("> %s\n" % INPUT)

    for round_ in range(1, engine.MAX_ROUNDS + 1):
        system = engine.build_system(tid, INPUT, detail="标准", round_=round_,
                                     max_rounds=engine.MAX_ROUNDS,
                                     scene=SCENE, glossary=True)
        parsed, _ = engine.send(conn, system, msgs, round_=round_, on_delta=None)
        if parsed.get("kind") == "ask":
            qs = parsed["ask"]
            out.append("## ② 第 %d 轮：它先反问（%d 题）\n" % (round_, len(qs)))
            for q in qs:
                out.append("**%s**" % q.get("q"))
                for o in q.get("opts") or []:
                    mark = "（★推荐）" if o.get("rec") else ""
                    out.append("- %s%s —— %s" % (o.get("label"), mark, o.get("desc")))
                out.append("")
            out.append("用户点选 / 作答：\n")
            out.append("> %s\n" % ANSWER)
            msgs = msgs + [{"role": "assistant", "content": parsed.get("raw") or ""},
                           {"role": "user", "content": ANSWER}]
            continue

        prompt = parsed.get("prompt") or ""
        out.append("## ③ 拿到的提示词（%d 字）\n" % len(prompt))
        out.append("```markdown")
        out.append(prompt.strip())
        out.append("```\n")
        out.append("## ④ 附带说明（原文）\n")
        rest = (parsed.get("raw") or "").replace(prompt, "").strip()
        out.append("```")
        out.append(rest[:1500])
        out.append("```")
        break

    path = os.path.join(ROOT, "video", "实例-编程记账.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    io.open(path, "w", encoding="utf-8").write("\n".join(out))
    print("\n".join(out[:60]))
    print("\n写入：", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
