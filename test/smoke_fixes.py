"""三条用户反馈的回归测试。

1. 配置 AI：已保存的 Key 再进详情页要能看到（打码），测试连接要能通
2. 主界面：点「系统提示词」这类分页，蓝色高亮必须跟着走
3. 侧栏：「+」要当场在场景下面长出一行新对话

用法：python test/smoke_fixes.py
"""

import os
import sys
import threading
import time
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

from ui import theme  # noqa: E402

theme.enable_dpi()

import mock_ai  # noqa: E402
from core import llm  # noqa: E402
from tools import shot  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.settings import SettingsWindow  # noqa: E402

PORT = 8902
TASKS = os.path.join(paths.data_dir(), sessions.FILE_NAME)
LOG = []
FAIL = []


def check(name, ok, extra=""):
    LOG.append(("PASS" if ok else "FAIL") + " · " + name + ("  " + extra if extra else ""))
    if not ok:
        FAIL.append(name)


def walk_cards(widget, out):
    """找出欢迎页里的圆角卡片（RoundCard）。"""
    from ui.widgets import RoundCard
    if isinstance(widget, RoundCard):
        out.append(widget)
    for c in widget.winfo_children():
        walk_cards(c, out)
    return out


# ------------------------------------------------------------------ 场景 1：配置
def test_settings(app, done):
    cfg = store.load_config()
    # 故意写成新手最容易写的样子：粘了完整端点、没有 /v1 之外的废话
    conn = store.clean_connection({
        "name": "本地假 AI",
        "provider": "自定义 / 中转站",
        "base_url": "  127.0.0.1:%d/v1/chat/completions/  " % PORT,
        "model": "mock-model",
        "protocol": "openai",
        "api_key": "sk-visible-key",
        "timeout": "120",
    })
    cfg["connections"] = [conn]
    cfg["active"] = conn["id"]
    store.save_config(cfg)

    check("地址被收拾干净", conn["base_url"] == "https://127.0.0.1:%d/v1" % PORT,
          conn["base_url"])

    # 换成本机能连的 http，再验一次解密回填
    conn["base_url"] = "http://127.0.0.1:%d/v1" % PORT
    cfg["connections"] = [conn]
    store.save_config(cfg)

    win = SettingsWindow(app)
    win.geometry("+120+60")
    win.attributes("-topmost", True)
    win.lift()

    def step1():
        stored = store.load_config()["connections"][0]
        win._show_detail(stored)
        app.update()
        shown = win._form["vars"]["key"].get()
        check("再进详情页能读到已存密钥", shown == "sk-visible-key", repr(shown))
        check("密钥默认是打码的", win._form["key_entry"].cget("show") == "•")
        shot.save_widget(win, os.path.join(ROOT, "test", "shot_fix_settings.png"))
        win._test(win._form["vars"])
        app.after(1600, step2)

    def step2():
        msg = win._status.cget("text")
        check("测试连接通过", msg.startswith("连通正常"), msg.replace("\n", " | "))
        check("结果里带实际请求地址", "实际请求" in msg and "/chat/completions" in msg)
        win.destroy()
        done()

    app.after(500, step1)


# ------------------------------------------------------------------ 场景 2/3：主窗
def test_main(app, done):
    # 干净起步
    for p in (TASKS,):
        if os.path.exists(p):
            os.remove(p)

    def step1():
        app.update()
        # --- 3. 点「+」立刻长出任务
        app._sidebar._groups["coding"]._add_task()
        app.after(300, step2)

    def step2():
        app.update()
        items = sessions.by_scene("coding")
        check("按 + 立刻落盘一个任务", len(items) == 1,
              "%d 个" % len(items))
        check("任务标题是「新对话」", (items[0]["title"] if items else "") == "新对话",
              items[0]["title"] if items else "-")
        tree = app._sidebar._groups["coding"]._items
        check("侧栏当场长出一行", len(tree) == 1, "%d 行" % len(tree))
        check("新建后自动展开场景",
              not app._sidebar._groups["coding"].is_collapsed())

        # --- 首页三张模式卡片：点在「文字」上必须也能切 ---
        # 以前绑定写在创建文字之前，只在卡片边缘的空白处点得动
        cards = []
        walk_cards(app._chat.inner, cards)
        check("首页有三张模式卡片", len(cards) == 3, "%d 张" % len(cards))
        dead = []
        for c in cards:
            for kid in c.body.winfo_children():
                if kid.winfo_class() == "Label" and not kid.bind("<Button-1>"):
                    dead.append(kid.cget("text"))
        check("卡片里的文字都挂了点击", not dead, ("点死角：" + str(dead)) if dead else "")

        before = app._mode
        target_card = cards[1]
        lab = [w for w in target_card.body.winfo_children()
               if w.winfo_class() == "Label"][0]
        lab.event_generate("<Button-1>", when="now", x=4, y=4)
        app.update()
        check("点卡片文字真的切换了模式", app._mode != before,
              "%s → %s" % (before, app._mode))
        # 切回来，免得影响下面按分页的断言
        app._mode_btns["task"]._command()
        app.update()
        app.after(200, step3)

    def step3():
        # --- 2. 点分页，高亮要跟着走
        btns = app._mode_btns
        check("三个分页都在", set(btns) == {"task", "system", "iterate"},
              str(list(btns)))
        target = btns["system"]
        target.focus_force()
        target.focus_set()
        app.update()
        # 真实鼠标是「按下 + 松开」两个事件，按钮动作挂在松开上，两个都要发
        target.event_generate("<Button-1>", when="now", x=6, y=6)
        target.event_generate("<ButtonRelease-1>", when="now", x=6, y=6)
        app.update()
        app.after(200, step3b)

    def step3b():
        check("点「系统提示词」后模式真的切了", app._mode == "system", app._mode)
        soft = "#EAF1FE"
        got = {k: b._colors[0] for k, b in app._mode_btns.items()}
        check("高亮移到系统提示词",
              got.get("system") == soft and got.get("task") != soft, str(got))
        check("选中项加粗",
              app._mode_btns["system"]._font.cget("weight") == "bold")
        shot.save_widget(app, os.path.join(ROOT, "test", "shot_fix_main.png"))
        app.after(100, step4)

    def step4():
        # 再点「迭代改进」，确认可以来回切（不是只能切一次）
        app._mode_btns["iterate"]._command()
        app.update()
        check("可以连续切换", app._mode == "iterate", app._mode)
        # 切回任务提示词
        app._mode_btns["task"]._command()
        app.update()

        # 空草稿不该被堆出来：再点一次 + 仍然只有一行
        app._sidebar._groups["coding"]._add_task()
        app.after(300, step5)

    def step5():
        items = sessions.by_scene("coding")
        check("连点 + 不会堆草稿", len(items) == 1, "%d 个" % len(items))
        done()

    app.after(900, step1)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), mock_ai.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.3)

    # 用户真实配置先藏起来，测完原样放回去
    backup_cfg = store.load_config()
    backup_tasks = None
    if os.path.exists(TASKS):
        with open(TASKS, "r", encoding="utf-8") as f:
            backup_tasks = f.read()

    app = MainWindow()
    app.geometry("+40+30")
    app.attributes("-topmost", True)
    app.deiconify()
    app.lift()

    def after_settings():
        app.after(400, lambda: test_main(app, finish))

    def finish():
        app.after(300, app.destroy)

    app.after(1000, lambda: test_settings(app, after_settings))
    app.mainloop()

    srv.shutdown()

    # 还原
    store.save_config(backup_cfg)
    for p in (TASKS,):
        if backup_tasks is None:
            if os.path.exists(p):
                os.remove(p)
        else:
            with open(p, "w", encoding="utf-8") as f:
                f.write(backup_tasks)

    print("\n".join(LOG))
    print("---")
    print("全部通过" if not FAIL else "失败 %d 项：%s" % (len(FAIL), FAIL))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
