"""轻提 · 本地提示词优化器（桌面版）

双击 轻提.exe 或 python app.py 启动。纯标准库，没有第三方依赖。
"""

import os
import sys
import time
import traceback

# 打包成窗口程序后 stdout/stderr 是 None，任何 print 都会抛 AttributeError。
# 必须在任何模块有机会输出之前替换掉。
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

if getattr(sys, "frozen", False):
    sys.path.insert(0, getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))

from core import paths  # noqa: E402

LOG_PATH = os.path.join(paths.data_dir(), "error.log")


def _log_exception(exc_type, exc_value, exc_tb):
    """窗口程序崩了没人看得见，落盘 + 弹框，否则用户只会觉得「点了没反应」。"""
    if issubclass(exc_type, KeyboardInterrupt):
        return
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("\n===== %s =====\n"
                    % time.strftime("%Y-%m-%d %H:%M:%S"))
            traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
    except OSError:
        pass
    try:
        import tkinter.messagebox as mb
        mb.showerror("轻提出错了",
                     "%s\n\n详细信息已写入：\n%s" % (exc_value, LOG_PATH))
    except Exception:
        pass


def _thread_exception(args):
    _log_exception(args.exc_type, args.exc_value, args.exc_traceback)


def main():
    sys.excepthook = _log_exception
    try:
        import threading
        threading.excepthook = _thread_exception
    except AttributeError:
        pass

    # 首次运行把出厂模板释放到 exe 旁边，之后归用户所有
    paths.seed_prompts()

    from core import templates
    templates.ensure_defaults()

    from ui import theme
    theme.enable_dpi()          # 必须在 Tk() 之前

    from ui.main_window import MainWindow
    app = MainWindow()
    app.mainloop()


if __name__ == "__main__":
    main()
