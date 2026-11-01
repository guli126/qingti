"""运行目录解析：兼容「源码直接跑」和「PyInstaller 单文件 exe」两种形态。

三个目录要分清：

  bundle_dir()  只读资源所在处。exe 模式下是 _MEIPASS 临时解压目录，
                源码模式下就是项目根。用来取出厂模板、静态页面。

  app_dir()     可写目录，也是用户能看见的地方。exe 模式 = exe 所在的文件夹，
                源码模式 = 项目根。prompts/ 放这里，用户才能拿记事本改。

  data_dir()    配置和历史。放在 %LOCALAPPDATA%\\轻提，不污染 exe 所在目录，
                也避免把程序放进 U 盘时写不进去。
"""

import os
import shutil
import sys

FROZEN = bool(getattr(sys, "frozen", False))

APP_NAME = "轻提"


def bundle_dir() -> str:
    """只读资源根目录。"""
    if FROZEN:
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def app_dir() -> str:
    """可写目录，用户可见。"""
    if FROZEN:
        return os.path.dirname(os.path.abspath(sys.executable))
    return bundle_dir()


def data_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, APP_NAME)
    try:
        os.makedirs(d, exist_ok=True)
        return d
    except OSError:
        d = os.path.join(app_dir(), "data")
        os.makedirs(d, exist_ok=True)
        return d


def user_docs_dir() -> str:
    """用户的「文档」目录（有 OneDrive 就跟着走，没有就退回 ~）。"""
    base = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    for name in ("Documents", "文档"):
        d = os.path.join(base, name)
        if os.path.isdir(d):
            return d
    return base


def history_dir() -> str:
    """会话记录单独放「文档\轻提」，跟安装目录、跟程序数据目录都不在一处。

    这样卸载/覆盖安装新版本、清 %LOCALAPPDATA%\轻提，都不会把聊天记录带走；
    用户想备份，直接去文档里拷一个 tasks.json 就行。
    """
    override = os.environ.get("QINGTI_HISTORY_DIR")
    d = override or os.path.join(user_docs_dir(), APP_NAME)
    try:
        os.makedirs(d, exist_ok=True)
        return d
    except OSError:
        return data_dir()


def web_dir() -> str:
    """静态页面：外置优先（方便改样式），否则读 exe 内部。"""
    for d in (os.path.join(app_dir(), "web"), os.path.join(bundle_dir(), "web")):
        if os.path.isdir(d):
            return d
    return os.path.join(bundle_dir(), "web")


def prompt_dir() -> str:
    """用户可编辑的模板目录。exe 第一次运行会自动释放。"""
    d = os.path.join(app_dir(), "prompts")
    os.makedirs(d, exist_ok=True)
    return d


def factory_prompt_dir() -> str:
    """出厂模板目录（只读）。exe 模式下在 _MEIPASS 里。"""
    return os.path.join(bundle_dir(), "prompts")


def default_dir() -> str:
    """出厂副本缓存，放数据目录，不跟用户模板混在一起。"""
    d = os.path.join(data_dir(), "_defaults")
    os.makedirs(d, exist_ok=True)
    return d


def seed_prompts(force: bool = False) -> list:
    """把出厂模板释放到 prompts/。

    只在目标文件不存在时拷贝——绝不覆盖用户改过的东西。
    force=True 用于刷新出厂副本缓存。
    返回实际写入的文件名列表。
    """
    src = factory_prompt_dir()
    dst = prompt_dir()
    if not os.path.isdir(src):
        return []
    written = []
    for name in sorted(os.listdir(src)):
        s = os.path.join(src, name)
        # 只认 .md 文件：_glossary.md 这种下划线开头的要保留（它是可编辑的词典），
        # 但 _defaults 之类的子目录要跳过
        if not name.endswith(".md") or not os.path.isfile(s):
            continue
        d = os.path.join(dst, name)
        if force or not os.path.isfile(d):
            try:
                shutil.copyfile(s, d)
                written.append(name)
            except OSError:
                pass
    return written
