"""UI 最终验证：欢迎页是否存在、发消息后是否消失、结果卡有无内嵌输入框。
两张截图：test/shot_final_welcome.png / test/shot_final_result.png
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "test"))

import _sandbox
_sandbox.isolate()

from core import store, paths, templates

conn = store.clean_connection({
    "name": "DeepSeek", "provider": "DeepSeek",
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-chat", "protocol": "openai", "api_key": "sk-local-demo",
})
cfg = store.load_config()
cfg["connections"] = [conn]
cfg["active"] = conn["id"]
store.save_config(cfg)

paths.seed_prompts()
templates.ensure_defaults()

from ui import theme
theme.enable_dpi()
from ui import main_window as mw
from tools import shot

PROMPT = ("## 目标\n做一个记录每月支出的桌面小工具，能按类别汇总并导出表格。\n\n"
          "## 使用场景\n个人记账，Windows 上用，不装开发环境。\n\n"
          "## 必须包含\n- 新增一笔支出\n- 按月、按类别汇总\n- 导出 xlsx")


def fake_send(conn, system, messages, round_=1, max_rounds=3,
              on_delta=None, retry=True):
    if on_delta:
        on_delta(PROMPT)
    return ({"kind": "prompt", "prompt": PROMPT, "raw": PROMPT, "ask": []},
            {"text": PROMPT, "truncated": False})


mw.engine.send = fake_send


def pump(win, sec=0.8):
    end = time.time() + sec
    while time.time() < end:
        win.update()
        time.sleep(0.01)


def main():
    win = mw.MainWindow()
    win.geometry("1180x760+60+40")
    win.attributes("-topmost", True)
    win.lift()
    pump(win, 1.0)
    shot.save_widget(win, os.path.join(ROOT, "test", "shot_final_welcome.png"))

    win._input.focus_force()
    win._clear_placeholder()
    win._input.insert("1.0", "帮我做个记录每月支出的东西")
    win._on_send()
    pump(win, 1.5)
    shot.save_widget(win, os.path.join(ROOT, "test", "shot_final_result.png"))

    print("welcome_frame:", win._welcome_frame)
    win.destroy()


if __name__ == "__main__":
    main()
