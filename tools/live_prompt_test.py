"""用真实模型跑一遍三个场景的提示词，检查输出是否真的可用。

不是单元测试（要联网、要花钱、结果不固定），是人工验收用的脚本：
跑完在 test/live_report.md 里留下每次的原始输出，方便逐条看质量。

用法：
    python tools/live_prompt_test.py            # 全部场景
    python tools/live_prompt_test.py work       # 只跑办公
"""

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import engine, llm, parse, store  # noqa: E402

CASES = [
    # (场景, 模式, 用户那句很随口的话)
    ("coding", "task", "我想做个能记账的东西，每个月花了多少钱能看明白"),
    ("coding", "system", "帮我写个系统提示词，让 AI 帮我检查代码有没有毛病"),
    ("work", "task", "帮我给领导写个这周的项目进度汇报"),
    ("work", "system", "想要个写周报的助手，语气别太假"),
    ("image", "t2i.general", "想要一张橘猫蹲在窗台上的图，下午的光"),
    ("image", "t2i.chinese", "做一张新中式茶饮海报，要高级感"),
    ("image", "t2i.json", "一张赛博朋克风格的城市夜景，用于游戏启动页"),
    ("image", "i2i.general", "把这张照片改成水彩画风格"),
    ("image", "i2i.text", "把海报上的“开业大吉”改成“周年庆”"),
]

def make_answer(questions):
    """按界面的真实行为作答：每题选推荐项，末尾补一句自由说明。"""
    lines = []
    for q in questions:
        opts = q.get("opts") or []
        pick = next((o for o in opts if o.get("rec")), opts[0] if opts else None)
        if pick:
            lines.append("- %s → %s" % (q.get("q"), pick.get("label")))
    return "我选了：\n" + "\n".join(lines) + \
        "\n\n补充：Windows 11，没装过开发工具，我就自己用。"

OUT = []


def say(s=""):
    print(s)
    OUT.append(s)


def one(conn, scene, mode, text):
    tid = engine.template_id(scene, mode)
    say("\n## %s / %s  `%s`" % (scene, mode, tid))
    say("> 用户：%s" % text)

    glossary = engine.SCENES[scene].get("glossary", False)
    msgs = [{"role": "user", "content": text}]
    parsed = None
    ok = True

    # 按真实轮次跑：能问就问，问完作答，轮次用尽必须出结果
    for round_ in range(1, engine.MAX_ROUNDS + 1):
        system = engine.build_system(tid, text, detail="标准", round_=round_,
                                     max_rounds=engine.MAX_ROUNDS,
                                     scene=scene, glossary=glossary)
        t0 = time.time()
        try:
            parsed, _ = engine.send(conn, system, msgs, round_=round_,
                                    on_delta=None)
        except llm.ChatError as e:
            say("**第 %d 轮请求失败**：%s" % (round_, e))
            return False
        dt = time.time() - t0

        if parsed.get("kind") == "ask":
            qs = parsed["ask"]
            say("- 第 %d 轮 %.1fs · 提问 %d 个：%s" %
                (round_, dt, len(qs), " / ".join(q.get("q", "") for q in qs)))
            for q in qs:
                opts = q.get("opts") or []
                rec = [o for o in opts if o.get("rec")]
                say("  - `%s` type=%s opts=%d rec=%d" %
                    (q.get("q"), q.get("type"), len(opts), len(rec)))
                if len(opts) < 3:
                    ok = False
                    say("    ⚠ 选项少于 3 个")
                if len(rec) != 1:
                    ok = False
                    say("    ⚠ 推荐项不是恰好 1 个")
            if round_ >= engine.MAX_ROUNDS:
                ok = False
                say("    ⚠ 已经是最后一轮还在提问")
                break
            answer = make_answer(qs)
            say("- 作答：%s" % "、".join(answer.splitlines()[1:4]))
            msgs = msgs + [{"role": "assistant", "content": parsed.get("raw") or ""},
                           {"role": "user", "content": answer}]
            continue

        say("- 第 %d 轮 %.1fs · kind=`%s` · %d 字" %
            (round_, dt, parsed.get("kind"),
             len(parsed.get("prompt") or "")))
        if parsed.get("kind") == "prompt":
            say("- 第 %d 轮给出结果（正常）" % round_)
        else:
            ok = False
            say("**未按格式输出**，原文：\n```\n%s\n```"
                % (parsed.get("raw") or "")[:400])
        break

    prompt = parsed.get("prompt") or ""
    if not prompt:
        ok = False
        say("**没有拿到提示词**")
    else:
        words = len(prompt)
        heads = [ln.strip("# ").strip() for ln in prompt.splitlines()
                 if ln.startswith("##")]
        say("- 提示词 %d 字，小节：%s" % (words, " / ".join(heads) or "无"))
        if scene == "image":
            if mode.endswith("json"):
                # JSON 模板本来就不该有句号，按「能不能解析 + 字段是否写满」判
                obj, err = None, ""
                try:
                    obj = json.loads(prompt)
                except Exception as e:  # noqa: BLE001
                    err = str(e)
                if err:
                    ok = False
                    say("    ⚠ 不是合法 JSON：%s" % err)
                elif not isinstance(obj, dict):
                    ok = False
                    say("    ⚠ 顶层不是 JSON 对象")
                else:
                    vals = obj.values()
                    texts = [v for v in vals if isinstance(v, str)]
                    say("- JSON 字段数：%d" % len(obj))
                    if len(obj) < 5:
                        ok = False
                        say("    ⚠ 字段太少，画面维度没填满")
                    if len(texts) != len(obj):
                        ok = False
                        say("    ⚠ 有字段不是字符串")
                    blank = [k for k, v in obj.items() if isinstance(v, str)
                             and not v.strip()]
                    if blank:
                        ok = False
                        say("    ⚠ 字段留空：%s" % "、".join(blank))
                    short = [k for k, v in obj.items()
                             if isinstance(v, str) and 0 < len(v.strip()) < 6
                             and k not in ("风格", "画幅")]
                    if short:
                        ok = False
                        say("    ⚠ 字段写得像标签：%s" % "、".join(short))
            else:
                # 图像提示词本来就该是连贯散文，不要求分节
                sentences = sum(prompt.count(ch) for ch in "。！？")
                say("- 句子数：%d" % sentences)
                if sentences < 3:
                    ok = False
                    say("    ⚠ 句子太少，不像完整画面")
            if words < 80:
                ok = False
                say("    ⚠ 太短，主体外的信息几乎没补")
            if words > 900:
                ok = False
                say("    ⚠ 太长，图像模型抓不住重点")
            banned = ("8k", "4k", "masterpiece", "best quality", "ultra detailed",
                      "octane render", "C4D", "Unreal Engine", "Pixar",
                      "artstation", "HDR")
            hit = [w for w in banned if w.lower() in prompt.lower()]
            if hit:
                ok = False
                say("    ⚠ 出现套话：%s" % "、".join(hit))
        else:
            if words < 150:
                ok = False
                say("    ⚠ 太短，可能没展开")
            if words > 1400:
                ok = False
                say("    ⚠ 太长，不像给人看的")
            if not heads:
                ok = False
                say("    ⚠ 没有分节结构")
        for bad in ("尽量", "适当", "合理地"):
            if bad in prompt:
                say("    ⚠ 出现模糊词「%s」" % bad)
        say("\n<details><summary>提示词全文</summary>\n\n```\n%s\n```\n\n</details>"
            % prompt)
        rest = (parsed.get("raw") or "").replace(prompt, "").strip()
        if rest:
            say("\n<details><summary>附带说明</summary>\n\n%s\n\n</details>" % rest)

    say("\n**结论：%s**" % ("通过" if ok else "需改进"))
    return ok


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    cfg = store.load_config()
    conn = engine.active_connection(cfg)
    if not conn:
        print("没有可用的 AI 配置")
        return 1
    say("# 真实模型提示词验收")
    say("\n- 模型：`%s`" % conn.get("model"))
    say("- 地址：`%s`" % conn.get("base_url"))
    say("- 时间：%s" % time.strftime("%Y-%m-%d %H:%M"))

    results = []
    for scene, mode, text in CASES:
        if only and only not in (scene, mode):
            continue
        results.append((scene, mode, one(conn, scene, mode, text)))

    good = sum(1 for _, _, ok in results if ok)
    say("\n---\n\n## 汇总\n")
    for scene, mode, ok in results:
        say("- %s / %s：%s" % (scene, mode, "通过" if ok else "需改进"))
    say("\n通过 %d / %d" % (good, len(results)))

    path = os.path.join(ROOT, "test", "live_report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(OUT))
    print("\n报告：", path)
    return 0 if good == len(results) else 2


if __name__ == "__main__":
    sys.exit(main())
