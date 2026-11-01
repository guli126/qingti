"""完整链路 UI 测试：回车发送 → 提问卡 → 跳过后给结果 → 任务落盘。

用 test/mock_ai.py 当假模型，不需要真 Key。
用法：python test/smoke_flow.py
"""

import os
import sys
import threading
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

sys.path.insert(0, os.path.join(ROOT, "test"))
from _sandbox import isolate          # noqa: E402

isolate()                             # 数据目录隔离到临时目录，绝不碰真实配置
sys.path.insert(0, os.path.join(ROOT, "test"))

from core import paths, sessions, store, templates  # noqa: E402

paths.seed_prompts()
templates.ensure_defaults()

import mock_ai  # noqa: E402
from ui import theme  # noqa: E402

theme.enable_dpi()

from ui.main_window import MainWindow  # noqa: E402
from ui.widgets import Button  # noqa: E402
from tools import shot  # noqa: E402

MOCK_PORT = 8899


def start_mock():
    srv = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), mock_ai.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def seed_conn():
    import copy
    cfg = copy.deepcopy(store.DEFAULT_CONFIG)
    cfg["connections"] = [store.clean_connection({
        "name": "Mock",
        "provider": "自定义 / 中转站",
        "base_url": "http://127.0.0.1:%d/v1" % MOCK_PORT,
        "model": "mock",
        "protocol": "openai",
        "api_key": "sk-mock",
        "timeout": 30,
    })]
    cfg["active"] = cfg["connections"][0]["id"]
    store.save_config(cfg)


def find_button(widget, text):
    if isinstance(widget, Button) and getattr(widget, "_text", "") == text:
        return widget
    for c in widget.winfo_children():
        got = find_button(c, text)
        if got:
            return got
    return None


def clear_tasks():
    p = os.path.join(paths.data_dir(), sessions.FILE_NAME)
    if os.path.exists(p):
        os.remove(p)


def main():
    srv = start_mock()
    backup = store.load_config()       # 真实配置先存着，测完还原
    seed_conn()
    clear_tasks()

    app = MainWindow()
    app.attributes("-topmost", True)
    app.lift()
    log = []

    def step_send():
        # 合成键盘事件必须让窗口真的拿到焦点，否则 Tk 直接丢掉按键
        app.deiconify()
        app.lift()
        app.focus_force()
        app._input.focus_set()
        app.update()
        app._clear_placeholder()
        app._input.insert("1.0", "帮我做个统计支出的东西")
        # 走真实的回车事件，验证 Enter 发送这条键绑定确实生效
        app._input.event_generate("<Return>", when="now")
        log.append("回车发送，输入框剩余 %d 字" % len(app._current_text()))
        app.after(2500, step_ask)

    def step_ask():
        app.update()
        try:
            shot.save_widget(app, os.path.join(ROOT, "test", "shot_ask.png"))
            log.append("提问卡已截图")
        except Exception as e:
            log.append("截图失败:%r" % e)

        btn = find_button(app._chat.inner, "就这些，开始吧")
        if not btn:
            log.append("没找到「就这些，开始吧」按钮")
            app.after(200, app.destroy)
            return
        log.append("找到跳过按钮，点击")
        btn._command()
        app.after(2500, step_result)

    def step_result():
        app.update()
        try:
            shot.save_widget(app, os.path.join(ROOT, "test", "shot_result.png"))
            log.append("结果卡已截图")
        except Exception as e:
            log.append("截图失败:%r" % e)
        log.append("最后提示词长度:%d" % len(app._last_prompt or ""))
        app.after(300, step_keys)

    def step_keys():
        # Ctrl+Enter 应该是换行而不是发送
        app.lift()
        app.focus_force()
        app._input.focus_set()
        app.update()
        app._input.event_generate("<Control-Return>", when="now", state=4)
        got = app._input.get("1.0", "end-1c")
        log.append("Ctrl+Enter 后输入框内容:%r" % got)
        app._input.delete("1.0", "end")
        app.after(600, step_verify)

    def step_verify():
        data = sessions.load()
        tasks = data.get("tasks") or []
        log.append("任务数:%d" % len(tasks))
        if tasks:
            t = tasks[-1]
            log.append("任务标题:%s / 场景:%s / 时间线:%d 条"
                       % (t.get("title"), t.get("scene"),
                          len(t.get("timeline") or [])))
        log.append("侧栏分组数:%d" % len(app._sidebar._groups))
        items = sum(len(g._items) for g in app._sidebar._groups.values())
        log.append("侧栏任务项:%d" % items)
        app.after(200, app.destroy)

    app.after(1200, step_send)
    app.mainloop()
    srv.shutdown()

    for line in log:
        print(line)

    # 清掉测试配置与测试任务，别影响用户真实数据
    store.save_config(backup)
    clear_tasks()


if __name__ == "__main__":
    main()
