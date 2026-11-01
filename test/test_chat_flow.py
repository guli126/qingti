"""聊天主流程回归测试：欢迎页该消失、结果卡不该再有输入框。

复现用户反馈的两个问题：
  1. 发出第一句话后，欢迎页（「说一句你想做什么」+ 三张模式卡）还留在
     聊天区顶部，被新消息一路顶上去。
  2. 结果卡片里又长出一个「还想改点什么」输入框，和底部输入框重复。

用法：python test/test_chat_flow.py
"""

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "test"))

import _sandbox  # noqa: E402

_sandbox.isolate()

from core import store  # noqa: E402

FAIL = []
LOG = []


def check(name, ok, extra=""):
    LOG.append(("PASS" if ok else "FAIL") + " · " + name + (("  " + extra) if extra else ""))
    if not ok:
        FAIL.append(name)


def seed_config():
    """在沙箱里放一份能通过 _ready_conn 的假配置。"""
    conn = store.clean_connection({
        "name": "测试", "provider": "自定义 / 中转站",
        "base_url": "https://example.invalid/v1",
        "model": "test-model", "protocol": "openai",
        "api_key": "sk-test-000",
    })
    cfg = store.load_config()
    cfg["connections"] = [conn]
    cfg["active"] = conn["id"]
    store.save_config(cfg)


seed_config()

import tkinter as tk  # noqa: E402

from core import engine  # noqa: E402
from ui import main_window as mw  # noqa: E402


def fake_send(conn, system, messages, round_=1, max_rounds=3,
              on_delta=None, retry=True):
    if on_delta:
        on_delta("正在整理…")
    parsed = {
        "kind": "prompt",
        "prompt": "## 目标\n把每月支出汇总成表格。\n\n## 完成标准\n能导入 xlsx。",
        "raw": "## 目标\n把每月支出汇总成表格。\n\n## 完成标准\n能导入 xlsx。",
        "ask": [],
    }
    return parsed, {"text": parsed["raw"], "truncated": False}


mw.engine.send = fake_send


def pump(win, sec=0.6):
    end = time.time() + sec
    while time.time() < end:
        win.update()
        time.sleep(0.01)


def all_text(widget):
    """递归收集控件上的文字，用来查欢迎页的残留文案。"""
    out = []
    try:
        if isinstance(widget, (tk.Label, tk.Button)):
            out.append(str(widget.cget("text")))
        elif isinstance(widget, tk.Text):
            out.append(widget.get("1.0", "end-1c"))
        for child in widget.winfo_children():
            out.extend(all_text(child))
    except tk.TclError:
        pass
    return out


def texts_in(chat):
    return "\n".join(all_text(chat.inner))


def main():
    win = mw.MainWindow()
    try:
        pump(win, 0.5)
        # 起始应是欢迎页
        check("启动显示欢迎页", "说一句你想做什么" in texts_in(win._chat))
        check("欢迎页有模式卡", win._welcome_frame is not None)

        # 模拟输入并发送
        win._input.focus_force()
        win._clear_placeholder()
        win._input.insert("1.0", "帮我做个统计每月支出的东西")
        win._on_send()
        pump(win, 1.2)

        chat_text = texts_in(win._chat)
        check("发送后欢迎标题消失", "说一句你想做什么" not in chat_text)
        check("发送后副标题消失",
              "说不清也没关系" not in chat_text)
        check("发送后模式卡提示消失",
              "左边「+」可以在对应的场景下开一个新任务" not in chat_text)
        check("欢迎页控件已销毁",
              win._welcome_frame is None
              or not win._welcome_frame.winfo_exists())
        check("用户气泡还在", "帮我做个统计每月支出的东西" in chat_text)
        check("结果卡出现", "生成结果" in chat_text)

        # 结果卡里不能有可输入的框（提示词正文是 disabled 的只读 Text）
        inputs = []
        for w in _descendants(win._chat.inner):
            if isinstance(w, tk.Entry):
                inputs.append(w)
            elif isinstance(w, tk.Text):
                try:
                    if str(w.cget("state")) != "disabled":
                        inputs.append(w)
                except tk.TclError:
                    pass
        check("结果区没有内嵌输入框", not inputs,
              "发现 %d 个" % len(inputs))
        check("结果区没有「还想改点什么」",
              "还想改点" not in chat_text)

        # 历史会话重进：不该再出现欢迎页
        win._apply_task(win._task)
        pump(win, 0.4)
        check("历史会话不显示欢迎页",
              "说一句你想做什么" not in texts_in(win._chat))

        # 新对话应重新出现欢迎页
        win._new_chat("coding")
        pump(win, 0.4)
        check("新对话重新显示欢迎页",
              "说一句你想做什么" in texts_in(win._chat))

        # 空草稿里切模式：欢迎页该按新模式重画，且仍只有一份
        win._pick_mode("system")
        pump(win, 0.4)
        chat_text = texts_in(win._chat)
        check("切模式后欢迎页只有一份",
              chat_text.count("说一句你想做什么") == 1,
              "出现 %d 次" % chat_text.count("说一句你想做什么"))
    finally:
        try:
            win.destroy()
        except tk.TclError:
            pass

    print("\n".join(LOG))
    print("---")
    if FAIL:
        print("失败 %d 项：%s" % (len(FAIL), "、".join(FAIL)))
        sys.exit(1)
    print("全部通过")


def _descendants(widget):
    out = []
    for child in widget.winfo_children():
        out.append(child)
        out.extend(_descendants(child))
    return out


if __name__ == "__main__":
    main()
