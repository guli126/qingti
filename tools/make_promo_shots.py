"""为宣传视频采集高质量界面截图（沙箱运行，不碰真实配置）。

产出（video/shots/）：
    welcome.png   欢迎页（三张模式卡）
    ask.png       提问卡（三道带选项的问题）
    result.png    结果卡（提示词正文）
    settings.png  AI 配置页
    editor.png    提示词编辑器

用法：python tools/make_promo_shots.py
"""

import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "test"))

import _sandbox                                   # noqa: E402
_sandbox.isolate()

from core import paths, store, templates          # noqa: E402

OUT = os.path.join(ROOT, "video", "shots")
os.makedirs(OUT, exist_ok=True)

conn = store.clean_connection({
    "name": "DeepSeek", "provider": "DeepSeek",
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-chat", "protocol": "openai", "api_key": "sk-sandbox-demo",
})
cfg = store.load_config()
cfg["connections"] = [conn]
cfg["active"] = conn["id"]
store.save_config(cfg)

paths.seed_prompts()
templates.ensure_defaults()

import tkinter as tk

from ui import theme                              # noqa: E402
theme.enable_dpi()

from ui import main_window as mw                  # noqa: E402
from tools import shot                            # noqa: E402

W, H = 1500, 940

ASK = [{
    "q": "这个记账工具主要给谁用？",
    "type": "single",
    "opts": [
        {"label": "我自己用", "desc": "功能够用就行，不用做账号体系", "rec": True},
        {"label": "给家人一起用", "desc": "要考虑多人共用一台电脑", "rec": False},
        {"label": "以后可能做成小工具卖", "desc": "要留出多用户和数据的余地", "rec": False},
    ],
}, {
    "q": "你更习惯怎么看账？",
    "type": "single",
    "opts": [
        {"label": "每月一张汇总表", "desc": "按月看总数和分类占比", "rec": True},
        {"label": "流水明细为主", "desc": "逐笔记录，随时翻", "rec": False},
        {"label": "图表趋势", "desc": "看几个月的变化曲线", "rec": False},
    ],
},
]

PROMPT = """## 目标
做一个记录每月支出的 Windows 桌面小工具，输入一笔支出后按月、按类别汇总，可导出 Excel。

## 使用场景
个人记账，装在 Windows 11 上，电脑里没有开发环境，双击就能用。

## 必须包含
- 新增一笔支出：金额、类别、日期、备注
- 月度汇总：总额 + 分类占比
- 分类管理：可增删类别
- 导出 Excel：一条命令导出当月账单

## 技术要求
- Python 3.10 + tkinter，零第三方依赖
- 数据存本地 SQLite，单文件数据库
- 界面中文，窗口默认 900x600

## 验收标准
1. 记账后立即在汇总表看到变化
2. 跨月数据互不干扰
3. 导出的 Excel 用 WPS 能直接打开
4. 关掉再开，数据还在"""

STATE = {"n": 0}


def fake_send(conn, system, messages, round_=1, max_rounds=3,
              on_delta=None, retry=True):
    STATE["n"] += 1
    if STATE["n"] == 1:
        if on_delta:
            on_delta("正在分析你的需求…")
        raw = "<<<ASK>>>\n" + __import__("json").dumps(ASK, ensure_ascii=False) + \
              "\n<<<ASK_END>>>"
        return ({"kind": "ask", "ask": ASK, "prompt": "", "raw": raw},
                {"text": raw, "truncated": False})
    if on_delta:
        on_delta(PROMPT)
    raw = "<<<PROMPT>>>\n" + PROMPT + "\n<<<PROMPT_END>>>"
    return ({"kind": "prompt", "ask": [], "prompt": PROMPT, "raw": raw},
            {"text": raw, "truncated": False})


mw.engine.send = fake_send


def pump(win, sec=0.8):
    end = time.time() + sec
    while time.time() < end:
        win.update()
        time.sleep(0.01)


def save(win, name):
    win.update()
    path = os.path.join(OUT, name)
    shot.save_widget(win, path)
    print("saved", name)


def main():
    win = mw.MainWindow()
    win.geometry("%dx%d+40+20" % (W, H))
    win.attributes("-topmost", True)
    win.lift()
    pump(win, 1.2)
    save(win, "welcome.png")

    win._input.focus_force()
    win._clear_placeholder()
    win._input.insert("1.0", "我想做个能记账的东西，每个月花了多少钱能看明白")
    win._on_send()
    pump(win, 1.6)
    save(win, "ask.png")

    # 记录「就这些，开始吧」按钮在整窗截图里的相对位置（给宣传片做点击演示用）
    win.update_idletasks()
    wx, wy = win.winfo_rootx(), win.winfo_rooty()
    ww, wh = win.winfo_width(), win.winfo_height()
    found = []

    def scan(w):
        try:
            label = getattr(w, "_text", None)
            if label is None:
                try:
                    label = w.cget("text")
                except tk.TclError:
                    label = None
            if str(label) == "就这些，开始吧":
                found.append(w)
            for c in w.winfo_children():
                scan(c)
        except tk.TclError:
            pass

    scan(win)
    hit = found[0] if found else None
    if hit is not None:
        cx = hit.winfo_rootx() - wx + hit.winfo_width() / 2
        cy = hit.winfo_rooty() - wy + hit.winfo_height() / 2
        meta = {"skip_rel": [round(cx / ww, 4), round(cy / wh, 4)],
                "size": [ww, wh]}
        io.open(os.path.join(OUT, "ask.json"), "w", encoding="utf-8").write(
            json.dumps(meta, ensure_ascii=False))
        print("skip button rel:", meta["skip_rel"])
    else:
        print("skip button not found")

    # 按界面真实路径作答：「就这些，开始吧」→ 出结果
    win._input.focus_force()
    win._clear_placeholder()
    win._input.insert("1.0", "就这些，开始吧")
    win._on_send()
    pump(win, 1.8)
    save(win, "result.png")

    # 配置页
    try:
        from ui.settings import SettingsWindow
        s = SettingsWindow(win)
        pump(win, 1.0)
        save(s, "settings.png")
        s.destroy()
    except Exception as e:                        # noqa: BLE001
        print("settings shot failed:", e)

    # 模板编辑器
    try:
        from ui.editor import EditorWindow
        e = EditorWindow(win)
        pump(win, 0.6)
        e._load("coding.task", force=True)
        pump(win, 0.8)
        save(e, "editor.png")
        e.destroy()
    except Exception as ex:                       # noqa: BLE001
        print("editor shot failed:", ex)

    win.destroy()


if __name__ == "__main__":
    main()
