"""侧栏任务树测试：任务落盘 → 恢复 → 折叠 → 重命名 → 删除。

全程不碰网络，只验证「任务 + 场景树」这套结构。
用法：python test/smoke_sidebar.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

sys.path.insert(0, os.path.join(ROOT, "test"))
from _sandbox import isolate          # noqa: E402

isolate()                             # 数据目录隔离到临时目录，绝不碰真实配置

from core import paths, sessions, store, templates  # noqa: E402

paths.seed_prompts()
templates.ensure_defaults()

from ui import theme  # noqa: E402

theme.enable_dpi()

from ui.main_window import MainWindow  # noqa: E402
from tools import shot  # noqa: E402


def clear_tasks():
    p = os.path.join(paths.data_dir(), sessions.FILE_NAME)
    if os.path.exists(p):
        os.remove(p)


def seed_tasks():
    plan = [
        ("coding", "记账小工具", "帮我做个统计支出的东西"),
        ("coding", "图片批量改名", "把一文件夹的图片按日期改名"),
        ("work", "本周项目周报", "给领导写本周项目进度汇报"),
        ("work", "客户邮件回执", "委婉地拒绝客户提前交付的要求"),
        ("image", "咖啡店封面图", "一只橘猫蹲在窗台上，午后斜光"),
    ]
    made = []
    for scene, title, text in plan:
        t = sessions.create(scene, title, "task")
        sessions.rename(t["id"], title)
        sessions.append(t["id"], {"role": "user", "text": text})
        sessions.append(t["id"], {
            "role": "result",
            "prompt": "## 目标\n" + text,
            "raw": "## 目标\n" + text,
            "truncated": False,
        })
        made.append(t["id"])
    sessions.set_active(made[0])
    return made


def main():
    clear_tasks()
    ids = seed_tasks()

    app = MainWindow()
    app.attributes("-topmost", True)
    app.lift()
    log = []

    def step_check():
        app.update()
        log.append("当前任务:%s" % ((app._task or {}).get("title"),))
        log.append("对话区子控件:%d" % len(app._chat.inner.winfo_children()))
        log.append("侧栏任务项:%d"
                   % sum(len(g._items) for g in app._sidebar._groups.values()))

        # 折叠「办公」
        app._sidebar._groups["work"]._toggle()
        app.update()
        data = sessions.load()
        log.append("办公折叠已存盘:%s" % sessions.collapsed("work", data))
        log.append("办公组已收起:%s"
                   % app._sidebar._groups["work"].is_collapsed())

        try:
            shot.save_widget(app, os.path.join(ROOT, "test", "shot_sidebar.png"))
            log.append("截图完成")
        except Exception as e:
            log.append("截图失败:%r" % e)
        app.after(300, step_edit)

    def step_edit():
        # 重命名 + 切任务
        sessions.rename(ids[1], "图片改名助手")
        app._sidebar.refresh()
        app._sidebar.set_active(ids[1])
        app._pick_task(ids[1])
        app.update()
        log.append("切到任务后标题:%s" % app._title_lab.cget("text"))
        log.append("时间线恢复卡片:%d" % len(app._chat.inner.winfo_children()))
        app.after(300, step_delete)

    def step_delete():
        sessions.remove(ids[1])
        app._sync_sidebar()
        app._on_task_changed()
        app.update()
        left = len(sessions.load().get("tasks") or [])
        log.append("删除后剩余任务:%d" % left)
        log.append("删除当前任务后回到:%s" % app._title_lab.cget("text"))
        app.after(200, app.destroy)

    app.after(900, step_check)
    app.mainloop()

    for line in log:
        print(line)
    clear_tasks()


if __name__ == "__main__":
    main()
