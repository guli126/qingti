"""提示词编辑器冒烟测试：打开 → 截图 → 切模板 → 保存 → 恢复默认。"""

import os
import sys

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
from ui.editor import EditorWindow  # noqa: E402
from tools import shot  # noqa: E402


def main():
    app = MainWindow()
    app.attributes("-topmost", True)
    log = []

    def step1():
        win = EditorWindow(app)
        win.attributes("-topmost", True)
        win.lift()
        log.append("编辑器已打开")
        app.after(1200, lambda: step2(win))

    def step2(win):
        app.update()
        shot.save_widget(win, os.path.join(ROOT, "test", "shot_editor.png"))
        log.append("截图完成")

        # 切到办公任务模板，改一行，保存，再恢复
        win._load("work.task", force=True)
        before = win._text.get("1.0", "end-1c")
        win._text.insert("end", "\n<!-- 测试标记 -->")
        win._save()
        after = templates.load_template("work.task")[1]
        log.append("保存生效: %s" % ("测试标记" in after))

        win._load("work.task", force=True)
        templates.reset_template("work.task")
        restored = templates.load_template("work.task")[1]
        log.append("恢复默认: %s" % ("测试标记" not in restored))
        log.append("正文长度 unchanged: %s" % (len(before) == len(restored)))
        app.after(200, app.destroy)

    app.after(1200, step1)
    app.mainloop()

    for line in log:
        print(line)


if __name__ == "__main__":
    main()
