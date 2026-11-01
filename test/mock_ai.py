"""本地假 AI，专门用来测试轻提的完整链路。

只用标准库，起在 8899。会按请求内容返回两种剧本：
  没提到「我的选择」→ 返回提问块（ASK）
  提到了          → 返回结果块（PROMPT）
流式分片故意切得很碎，并混入 reasoning_content 与 <thinking> 标签，
用来验证「思考过滤」和「跨分片拼装」是否可靠。
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ASK_TEXT = """我先确认两件事，免得做出来不是你要的。

<<<ASK>>>
[
  {"q": "你的程序要在哪里运行？", "type": "single", "opts": [
    {"label": "自己电脑上双击就能用", "desc": "最简单，不用装服务器"},
    {"label": "浏览器打开的网页", "desc": "能发给别人用，但要多写前端", "rec": true},
    {"label": "放到服务器给别人访问", "desc": "要买服务器和维护，新手不建议"}
  ]},
  {"q": "要包含哪些功能？", "type": "multi", "opts": [
    {"label": "记一笔支出", "desc": "手动输入金额和类别", "rec": true},
    {"label": "按月汇总", "desc": "自动算每月合计", "rec": true},
    {"label": "导出表格", "desc": "导出成 xlsx 或 csv"}
  ]}
]
<<<ASK_END>>>"""

PROMPT_TEXT = """### ① 我理解的任务

你想做一个自己用的记账小工具，能在浏览器里打开，手动记一笔支出，并且能按月份看到总共花了多少。

### ② 优化后的提示词

<<<PROMPT>>>
## 目标
做一个能在浏览器打开的单页记账工具：可以手动记一笔支出（金额、类别、日期、备注），并能按月份汇总合计。

## 背景
只有我自己用，不需要登录和权限。现在是用手机备忘录记，月底手算，经常算错。
运行环境：Windows 电脑本地打开，优先用单个 HTML 文件，双击即用。

## 约束
- 技术栈由你选择，但选完先用一句话说明理由，并确保不需要安装任何东西
- 数据存在浏览器本地（localStorage），关掉页面再打开数据还在
- 不许引入任何需要联网加载的库，断网也要能用
- 金额只接受正数，输入非法时给出提示而不是静默失败
- 用户水平：新手，出现术语时用一句大白话解释

## 完成标准
1. 打开页面就能看到输入框和本月合计
2. 记一笔后立即出现在列表里，合计同步变化
3. 刷新页面后数据仍在
4. 切换月份能看到对应月份的记录和合计
5. 金额填成文字或负数时，有明确提示且不会写入

## 交付方式
先给出文件结构和整体思路，等我确认后再写代码；代码一次只给一个文件。
<<<PROMPT_END>>>

### ③ 我用到和猜到的

- 术语解释：`localStorage`＝浏览器自带的一小块本地存储，关掉页面数据还在
- 我替你猜的：用单个 HTML 文件而不是框架。如果不合意，改这里：「技术栈由你选择」那句
- 我替你猜的：数据只存本地、不联网同步。如果不合意，在「约束」里加一句要云同步"""


PROSE_TEXT = """我先问你几个问题，免得做出来不是你要的：

1. 你的程序要在哪里运行？是双击就能用的电脑程序，还是浏览器打开的网页？
2. 要包含哪些功能？记一笔支出？按月汇总？导出表格？
3. 数据存哪里？只存本地，还是要同步到手机？

你回我一下这几点，我再给你写详细的提示词。"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {}
        # 把整段请求拍平，看用户回没回答。
        # 「我的选择」= 点了确认；「直接给结果」= 点了跳过，两种都该出结果。
        flat = json.dumps(payload, ensure_ascii=False)
        answered = ("我的选择" in flat) or ("直接给结果" in flat)
        # 用户说「跑偏」时第一次故意不按格式回，用来验证自动补救
        nudged = "上一条回复没有按" in flat
        forced = "提问次数已经用完了" in flat
        if forced:
            # 被强制出结果时才给提示词
            text = PROMPT_TEXT
        elif nudged:
            text = ASK_TEXT
        elif "跑偏" in flat and not answered:
            text = PROSE_TEXT
        elif "赖着" in flat:
            # 「赖着提问」的模型：轮次用尽仍在提问，只能靠强制催一次救回来
            text = ASK_TEXT
        else:
            text = PROMPT_TEXT if answered else ASK_TEXT

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def send(obj):
            self.wfile.write(("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8"))
            self.wfile.flush()

        # 先来一段「思考」，前端应当把它丢掉
        send({"choices": [{"delta": {"reasoning_content": "用户想要记账工具……"}}]})
        send({"choices": [{"delta": {"content": "<thinking>这里是想被剥掉的思考</thinking>"}}]})

        # 正文切碎，每 7 个字符一片，专门制造跨分片的标签/标记
        for i in range(0, len(text), 7):
            send({"choices": [{"delta": {"content": text[i:i + 7]}}]})

        send({"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"total_tokens": 123}})
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    print("mock ai on %d" % port)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
