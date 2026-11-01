"""设置窗口冒烟测试：造两条假配置，截图列表页和详情页。

用法：python test/smoke_settings.py
测完会把配置清空（不碰真实密钥，因为本来就只在测试环境跑）。
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

sys.path.insert(0, os.path.join(ROOT, "test"))
from _sandbox import isolate          # noqa: E402

isolate()                             # 数据目录隔离到临时目录，绝不碰真实配置

from core import paths, providers, store, templates  # noqa: E402

paths.seed_prompts()
templates.ensure_defaults()

from ui import theme  # noqa: E402

theme.enable_dpi()

from ui.main_window import MainWindow  # noqa: E402
from ui.settings import SettingsWindow  # noqa: E402
from tools import shot  # noqa: E402

SEED = [("DeepSeek 主号", "DeepSeek"),
        ("通义千问", "通义千问（阿里云百炼）"),
        ("中转站", "自定义 / 中转站")]


def seed_config():
    cfg = store.load_config()
    cfg["connections"] = []
    for name, prov in SEED:
        preset = providers.PROVIDERS[prov]
        conn = store.clean_connection({
            "name": name,
            "provider": prov,
            "base_url": preset["base_url"] or "https://api.example.com/v1",
            "model": preset["model"] or "custom-model",
            "protocol": preset["protocol"],
            "api_key": "sk-test-fake-key",
            "timeout": 60,
        })
        cfg["connections"].append(conn)
    cfg["active"] = cfg["connections"][0]["id"]
    store.save_config(cfg)
    return cfg


def main():
    # 先把用户真实配置存一份，测完放回去——跑测试不该把人家填好的东西冲掉
    backup = store.load_config()
    seed_config()
    app = MainWindow()
    app.geometry("+50+20")
    app.attributes("-topmost", True)

    outcome = {}

    def step1():
        win = SettingsWindow(app)
        win.geometry("+160+60")
        win.attributes("-topmost", True)
        win.lift()
        outcome["win"] = win
        app.after(900, lambda: step2(win))

    def step2(win):
        app.update()
        shot.save_widget(win, os.path.join(ROOT, "test", "shot_settings_list.png"))
        # 点「新增 AI 配置」进详情页
        win._new_conn()
        app.after(900, lambda: step3(win))

    def step3(win):
        app.update()
        shot.save_widget(win, os.path.join(ROOT, "test", "shot_settings_detail.png"))
        outcome["ok"] = True
        app.after(200, app.destroy)

    app.after(1200, step1)
    app.mainloop()

    print("设置窗口测完:", outcome.get("ok"))
    print("列表页：test/shot_settings_list.png")
    print("详情页：test/shot_settings_detail.png")

    # 还原用户原来的配置
    store.save_config(backup)


if __name__ == "__main__":
    main()
