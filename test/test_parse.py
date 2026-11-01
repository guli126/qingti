"""回复解析的单元测试（不开窗口，秒出结果）。

重点是那类「模型明明给了选项，界面却只显示一串原文」的坑：
JSON 正文里带中文引号、用中文引号当分隔符、忘写标记、尾逗号、包了代码围栏。

用法：python test/test_parse.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import parse  # noqa: E402

FAIL = []
LOG = []


def check(name, ok, extra=""):
    LOG.append(("PASS" if ok else "FAIL") + " · " + name + (("  " + extra) if extra else ""))
    if not ok:
        FAIL.append(name)


# 用户真实遇到的那一段：标记齐全、JSON 合法，正文里带中文引号
RAW_USER = """ <<<ASK>>>
[
  {
    "q": "这个套壳 App 是给哪个手机系统装的？",
    "type": "single",
    "opts": [
      {"label": "安卓手机", "desc": "在开发者选项里开启模拟定位就能用，门槛最低", "rec": true},
      {"label": "苹果手机", "desc": "苹果限制很严，基本要越狱或用电脑调试，不建议新手碰"},
      {"label": "两边都要", "desc": "工作量翻倍，苹果那侧还有很多绕不开的坑"}
    ]
  },
  {
    "q": "你说的“套壳”，是想把什么包进 App 里？",
    "type": "single",
    "opts": [
      {"label": "包现成软件", "desc": "找一个现成的开源项目，换图标、换界面，重新打包", "rec": true},
      {"label": "包网页链接", "desc": "把一个网址包进 App 外壳"},
      {"label": "核心功能自写", "desc": "虚拟定位的代码自己写，工作量最大"}
    ]
  },
  {
    "q": "这个 App 做出来给谁用？",
    "type": "single",
    "opts": [
      {"label": "只有我自己用", "desc": "不涉及上架和分发", "rec": true},
      {"label": "装到朋友手机上", "desc": "要打成安装文件发出去"},
      {"label": "上架应用商店", "desc": "虚拟定位类功能大概率过不了审核"}
    ]
  }
]
<<<ASK_END>>>"""

# 中文引号被当成 JSON 分隔符（模型手写 JSON 时常见）
RAW_CURLY_DELIM = """<<<ASK>>>
[
  {“q”: “要什么风格？”, “type”: “single”, “opts”: [
    {“label”: “简约”, “desc”: “白底黑字”, “rec”: true},
    {“label”: “花哨”, “desc”: “颜色多一点”}
  ]}
]
<<<ASK_END>>>"""

# 忘了写标记，整段就是一个数组
RAW_NO_MARK = """[
  {"q": "要多大的？", "opts": [
    {"label": "小", "desc": ""},
    {"label": "大", "desc": "", "rec": true}
  ]}
]"""

# 尾逗号 + 代码围栏
RAW_SLOPPY = """```json
<<<ASK>>>
[
  {"q": "用什么语言？", "opts": [
    {"label": "Python", "desc": "你熟", "rec": true},
    {"label": "JavaScript", "desc": "能直接跑网页"},
  ]},
]
<<<ASK_END>>>
```"""

RAW_PROMPT = """### 优化后的提示词

<<<PROMPT>>>
## 目标
做个记账工具
<<<PROMPT_END>>>

### 说明
随便聊聊。"""

RAW_TEXT = "我先问你几个问题：1. 你要什么？2. 给谁用？"

# 真实踩到的：模型在说明里先画一个空的提示词壳，正文在后面。
# 以前取第一个匹配，于是拿到空串，整条回复被判成「没按格式」。
RAW_EMPTY_SHELL_FIRST = """### ② 优化后的提示词

<<<PROMPT>>>
<<<PROMPT_END>>>

### ③ 正式的提示词

<<<PROMPT>>>
## 目标
把每周进展整理成周报，四段结构，300 字以内。
<<<PROMPT_END>>>"""

# 同一段里出现两个 ASK，第二个才是有内容的
RAW_DOUBLE_ASK = """<<<ASK>>>
[]
<<<ASK_END>>>

<<<ASK>>>
[{"q": "给谁看？", "opts": [
  {"label": "领导", "desc": "", "rec": true},
  {"label": "客户", "desc": ""},
  {"label": "同事", "desc": ""}
]}]
<<<ASK_END>>>"""


def main():
    r = parse.parse_reply(RAW_USER)
    check("带中文引号的正文不再解析失败", r["kind"] == "ask", r["kind"])
    check("三题都解析出来", len(r["ask"]) == 3, "%d 题" % len(r["ask"]))
    if r["ask"]:
        q2 = r["ask"][1]
        check("正文里的中文引号原样保留",
              "“套壳”" in q2["q"], q2["q"])
        recs = [o["label"] for o in r["ask"][0]["opts"] if o["rec"]]
        check("推荐标记只留一个", recs == ["安卓手机"], str(recs))

    r = parse.parse_reply(RAW_CURLY_DELIM)
    check("中文引号当分隔符也能认", r["kind"] == "ask" and len(r["ask"]) == 1,
          "%s %d" % (r["kind"], len(r["ask"])))

    r = parse.parse_reply(RAW_NO_MARK)
    check("没写标记的裸数组也能认", r["kind"] == "ask" and len(r["ask"]) == 1,
          "%s %d" % (r["kind"], len(r["ask"])))

    r = parse.parse_reply(RAW_SLOPPY)
    check("围栏 + 尾逗号能认", r["kind"] == "ask" and len(r["ask"]) == 1,
          "%s %d" % (r["kind"], len(r["ask"])))

    r = parse.parse_reply(RAW_PROMPT)
    check("提示词块不受影响", r["kind"] == "prompt" and "记账" in (r["prompt"] or ""),
          r["kind"])

    r = parse.parse_reply(RAW_EMPTY_SHELL_FIRST)
    check("空壳在前也能取到真正的提示词",
          r["kind"] == "prompt" and "周报" in (r["prompt"] or "")
          and len(r["prompt"] or "") > 20, r["kind"])

    r = parse.parse_reply(RAW_DOUBLE_ASK)
    check("多个 ASK 取有内容的那个",
          r["kind"] == "ask" and len(r["ask"]) == 1, "%s %d" % (r["kind"], len(r["ask"])))

    r = parse.parse_reply(RAW_EMPTY_SHELL_FIRST + "\n\n" + RAW_DOUBLE_ASK)
    check("同时有提问和提示词时提问优先", r["kind"] == "ask", r["kind"])
    r = parse.parse_reply(RAW_EMPTY_SHELL_FIRST + "\n\n" + RAW_DOUBLE_ASK,
                          prefer="prompt")
    check("prefer=prompt 时改为取提示词", r["kind"] == "prompt", r["kind"])

    r = parse.parse_reply(RAW_TEXT)
    check("纯大白话仍是 text", r["kind"] == "text" and r["ask"] == [], r["kind"])

    r = parse.parse_reply("")
    check("空回复不炸", r["kind"] == "text")

    print("\n".join(LOG))
    print("---")
    print("全部通过" if not FAIL else "失败 %d 项：%s" % (len(FAIL), FAIL))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
