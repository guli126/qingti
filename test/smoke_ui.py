"""界面冒烟测试：启动主窗口，若干秒后自动关闭，可选截图。

用法：
    python test/smoke_ui.py            # 默认看 6 秒后关掉
    python test/smoke_ui.py 4 --shot   # 4 秒后截一张 test/shot_main.png
"""

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

sys.path.insert(0, os.path.join(ROOT, "test"))
from _sandbox import isolate          # noqa: E402

isolate()                             # 数据目录隔离到临时目录，绝不碰真实配置

from core import paths, templates  # noqa: E402

paths.seed_prompts()
templates.ensure_defaults()

from ui import theme  # noqa: E402

theme.enable_dpi()

from ui.main_window import MainWindow  # noqa: E402

SECONDS = 6.0
SHOT = "--shot" in sys.argv
for a in sys.argv[1:]:
    try:
        SECONDS = float(a)
    except ValueError:
        pass


def main():
    app = MainWindow()
    app.geometry("+70+30")
    app.attributes("-topmost", True)
    app.lift()

    started = time.time()
    report = {}

    def finish():
        report["children"] = len(app._chat.inner.winfo_children())
        report["size"] = (app.winfo_width(), app.winfo_height())
        if SHOT:
            from tools import shot
            app.update()
            path = os.path.join(ROOT, "test", "shot_main.png")
            try:
                shot.save_widget(app, path)
                report["shot"] = path
            except Exception as e:
                report["shot_error"] = repr(e)
        app.destroy()

    app.after(int(SECONDS * 1000), finish)
    app.mainloop()

    print("UI ok, 存活 %.1fs" % (time.time() - started))
    print("窗口尺寸：%s" % (report.get("size"),))
    print("滚动区子控件数：%d" % report.get("children", -1))
    if report.get("shot"):
        print("截图：%s" % report["shot"])
    if report.get("shot_error"):
        print("截图失败：%s" % report["shot_error"])


if __name__ == "__main__":
    main()
