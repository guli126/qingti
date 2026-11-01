"""滚轮与历史存储的回归测试。

盯两件事：
  1. 鼠标不用先点一下，进入聊天区（甚至只是停在里面的卡片上）滚轮就能滚；
  2. 聊天记录存在「文档\\轻提」，不在安装目录/配置目录，重装不会被清。
"""

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "test"))

import _sandbox                                    # noqa: E402
_sandbox.isolate()

FAIL, LOG = [], []


def check(name, ok, extra=""):
    LOG.append(("PASS" if ok else "FAIL") + " · " + name + (("  " + extra) if extra else ""))
    if not ok:
        FAIL.append(name)


# ---------------------------------------------------------------- 存储位置
from core import paths, sessions                   # noqa: E402

data = os.path.abspath(paths.data_dir())
hist = os.path.abspath(paths.history_dir())
check("历史目录与配置目录不同", data != hist, "%s vs %s" % (data, hist))
check("历史目录不在配置目录里", not hist.startswith(data + os.sep), hist)
check("历史文件名正确", sessions._path().endswith("tasks.json"))
check("历史文件落在历史目录",
      os.path.dirname(os.path.abspath(sessions._path())) == hist)

# 迁移：老位置有、新位置没有 → 搬过来，并留 .migrated 底
legacy = sessions.legacy_path()
os.makedirs(os.path.dirname(legacy), exist_ok=True)
with open(legacy, "w", encoding="utf-8") as f:
    f.write('{"tasks": [{"id": "t1", "title": "旧记录"}], "collapsed": {}, "active": "t1"}')

moved = sessions.migrate_legacy()
check("老记录自动迁移", moved)
check("迁移后新文件存在", os.path.isfile(sessions._path()))
check("迁移保留老文件备份", os.path.isfile(legacy + ".migrated"))
got = sessions.load()
check("迁移后能读到旧任务", any(t.get("title") == "旧记录" for t in got["tasks"]))

# 已有新记录时不覆盖
sessions.save({"tasks": [{"id": "t2", "title": "新记录"}], "collapsed": {}, "active": "t2"})
check("二次迁移不会覆盖", sessions.migrate_legacy() is False)
check("新记录仍在", any(t.get("title") == "新记录" for t in sessions.load()["tasks"]))


# ---------------------------------------------------------------- 滚轮
import tkinter as tk                               # noqa: E402
from ui import widgets                             # noqa: E402


class FakeWheel:
    def __init__(self, widget):
        self.widget = widget
        self.x_root = 10
        self.y_root = 10
        self.delta = -120
        self.num = None


def pump(win, sec=0.4):
    end = time.time() + sec
    while time.time() < end:
        win.update()
        time.sleep(0.01)


root = tk.Tk()
root.geometry("420x300+80+80")
frame = widgets.ScrollFrame(root)
frame.pack(fill="both", expand=True)
for i in range(40):
    tk.Label(frame.inner, text="第 %d 行内容" % i, bg="#ffffff").pack(fill="x")
pump(root, 0.5)
frame.canvas.update_idletasks()
frame.canvas.configure(scrollregion=frame.canvas.bbox("all"))

check("滚动区域超高", frame.inner.winfo_reqheight() > frame.canvas.winfo_height())

before = frame.canvas.yview()[0]


class Stub:
    """模拟指针停在内部某个 Label 上（没有进过 canvas 的 <Enter>）。"""
    def __init__(self, widget):
        self.widget = widget
        self.x_root = widget.winfo_rootx() + 5
        self.y_root = widget.winfo_rooty() + 3
        self.delta = -120
        self.num = None


child = frame.inner.winfo_children()[5]
hit = widgets._wheel_dispatch(Stub(child))
pump(root, 0.2)
after = frame.canvas.yview()[0]

check("指针在内部控件上也能滚", after > before,
      "before=%.3f after=%.3f" % (before, after))
check("命中后返回 break", hit == "break")

# 往上滚回到顶（指针固定在滚动区域中央）
class UpStub(Stub):
    def __init__(self):
        self.widget = frame.canvas
        self.x_root = frame.canvas.winfo_rootx() + frame.canvas.winfo_width() // 2
        self.y_root = frame.canvas.winfo_rooty() + frame.canvas.winfo_height() // 2
        self.delta = 120
        self.num = None


for _ in range(60):
    widgets._wheel_dispatch(UpStub())
pump(root, 0.2)
check("反方向可滚回顶部", frame.canvas.yview()[0] <= 0.01,
      "yview=%.3f" % frame.canvas.yview()[0])

# 指针在窗口外（别的区域）不应该被这个容器吃掉
outside = Stub(root)
outside.x_root, outside.y_root = 5, 5
check("指针不在区域内不乱滚", widgets._wheel_dispatch(outside) is None)


# ---------------------------------------------------------------- 真窗口里滚一下
from core import store as _store

def seed_config():
    conn = _store.clean_connection({
        "name": "测试", "provider": "自定义 / 中转站",
        "base_url": "https://example.invalid/v1",
        "model": "test-model", "protocol": "openai",
        "api_key": "sk-test-000",
    })
    cfg = _store.load_config()
    cfg["connections"] = [conn]
    cfg["active"] = conn["id"]
    _store.save_config(cfg)

seed_config()

from ui import main_window as mw

LONG = "## 目标" + chr(10) + chr(10).join("- 第 %d 条约束" % i for i in range(30))

def fake_send(conn, system, messages, round_=1, max_rounds=3,
              on_delta=None, retry=True):
    if on_delta:
        on_delta(LONG)
    return ({"kind": "prompt", "prompt": LONG, "raw": LONG, "ask": []},
            {"text": LONG, "truncated": False})

mw.engine.send = fake_send
win = mw.MainWindow()
win.geometry("900x600+60+60")
pump(win, 0.8)
win._input.focus_force()
win._clear_placeholder()
win._input.insert("1.0", "帮我做个统计每月支出的东西")
win._on_send()
pump(win, 1.2)

chat = win._chat
chat.canvas.update_idletasks()
chat.canvas.configure(scrollregion=chat.canvas.bbox("all"))
check("真窗口聊天区可滚动", chat.inner.winfo_reqheight() > chat.canvas.winfo_height())

kids = chat.inner.winfo_children()
target = kids[0] if kids else chat.canvas
before = chat.canvas.yview()[0]

class ChatWheel:
    def __init__(self, w):
        self.widget = w
        self.x_root = w.winfo_rootx() + 5
        self.y_root = w.winfo_rooty() + 5
        self.delta = 120          # 新消息后自动停在底部，往上滚才有位移
        self.num = None

widgets._wheel_dispatch(ChatWheel(target))
pump(win, 0.3)
after = chat.canvas.yview()[0]
check("没先点一下，停在卡片上也能滚", after < before,
      "before=%.3f after=%.3f" % (before, after))
win.destroy()


print("\n".join(LOG))
print("---")
if FAIL:
    print("失败 %d 项：%s" % (len(FAIL), "、".join(FAIL)))
    sys.exit(1)
print("全部通过")
