"""配色、字体、DPI、ttk 样式。

想换外观只改这一个文件。所有界面都从这里取色，不许在别处硬编码颜色。
"""

import ctypes
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# ------------------------------------------------------------------ 颜色

BG = "#F5F6F8"          # 窗口底色
CARD = "#FFFFFF"        # 卡片 / 输入框
SIDEBAR = "#1D2430"     # 左侧导航（深色，和白色主区拉开层次）
SIDEBAR_HOVER = "#28313F"
SIDEBAR_ACTIVE = "#2F6FED"
SIDEBAR_TEXT = "#A9B2C0"
SIDEBAR_TEXT_ON = "#FFFFFF"

PRIMARY = "#2F6FED"
PRIMARY_HOVER = "#2559C9"
PRIMARY_SOFT = "#EAF1FE"   # 浅蓝底，用于选中态
TEXT = "#1A1D21"
TEXT_SUB = "#5B6472"
MUTED = "#8A929E"
BORDER = "#E2E5EA"
BORDER_STRONG = "#C9CFD8"

OK = "#12A45B"
WARN = "#C2760A"
ERR = "#D93F3F"
ERR_SOFT = "#FDECEC"

BUBBLE_USER = "#2F6FED"
BUBBLE_AI = "#FFFFFF"

# ------------------------------------------------------------------ 尺寸

RADIUS = 10
PAD = 16

# ------------------------------------------------------------------ DPI


def enable_dpi() -> None:
    """必须在 Tk() 之前调用，否则高分屏上整个界面是糊的。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def apply_scaling(root: tk.Misc) -> None:
    """让 pt 字号对应真实物理尺寸。"""
    try:
        dpi = root.winfo_fpixels("1i")
        if dpi and dpi > 50:
            root.tk.call("tk", "scaling", dpi / 72.0)
    except Exception:
        pass


# ------------------------------------------------------------------ 字体

_UI_CANDIDATES = ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "Arial")
_MONO_CANDIDATES = ("Consolas", "Cascadia Mono", "Courier New")

_cache: dict = {}
_ui_family = "TkDefaultFont"
_mono_family = "Courier"


def init_fonts(root: tk.Misc) -> None:
    """挑出本机真实存在的字体，避免静默回退成难看的默认字体。"""
    global _ui_family, _mono_family
    have = set(tkfont.families(root))
    for fam in _UI_CANDIDATES:
        if fam in have:
            _ui_family = fam
            break
    for fam in _MONO_CANDIDATES:
        if fam in have:
            _mono_family = fam
            break
    try:
        # Tk 默认字体的行高偏挤，统一抬一点
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
            tkfont.nametofont(name).configure(family=_ui_family, size=10)
    except Exception:
        pass


def font(size: int = 10, bold: bool = False, mono: bool = False,
         italic: bool = False) -> tkfont.Font:
    key = (size, bold, mono, italic)
    f = _cache.get(key)
    if f is None:
        fam = _mono_family if mono else _ui_family
        f = tkfont.Font(family=fam, size=size,
                        weight="bold" if bold else "normal",
                        slant="italic" if italic else "roman")
        _cache[key] = f
    return f


# 常用字号，写界面时直接引用
F_TITLE = (14, True)
F_SUB = (10, False)
F_BODY = (10, False)
F_SMALL = (9, False)
F_BOLD = (10, True)


# ------------------------------------------------------------------ ttk 样式


def apply_ttk(root: tk.Misc) -> None:
    """把 ttk 控件改成跟主题一致的样子（滚动条、下拉框、列表）。"""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")   # clam 是唯一能被彻底改色的内置主题
    except tk.TclError:
        pass

    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=CARD)
    style.configure("Side.TFrame", background=SIDEBAR)

    style.configure("TLabel", background=BG, foreground=TEXT, font=font(10))
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=font(9))
    style.configure("Card.TLabel", background=CARD, foreground=TEXT, font=font(10))
    style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED, font=font(9))
    style.configure("H1.TLabel", background=BG, foreground=TEXT, font=font(14, True))
    style.configure("H2.TLabel", background=CARD, foreground=TEXT, font=font(11, True))

    # 滚动条：细、无箭头、悬停才明显
    style.configure("Slim.Vertical.TScrollbar",
                    background=BORDER_STRONG, troughcolor=BG,
                    borderwidth=0, arrowsize=0, width=8)
    style.map("Slim.Vertical.TScrollbar",
              background=[("active", MUTED)])

    # 深色侧栏上的滚动条：trough 必须跟侧栏同色，否则会看到一条白边
    style.configure("Dark.Vertical.TScrollbar",
                    background="#3A4454", troughcolor=SIDEBAR,
                    borderwidth=0, arrowsize=0, width=8)
    style.map("Dark.Vertical.TScrollbar",
              background=[("active", "#4C586C")])

    # 下拉框
    style.configure("TCombobox",
                    fieldbackground=CARD, background=CARD,
                    foreground=TEXT, arrowcolor=TEXT_SUB,
                    bordercolor=BORDER_STRONG, lightcolor=BORDER_STRONG,
                    darkcolor=BORDER_STRONG, borderwidth=1,
                    padding=(8, 6), relief="flat")
    style.map("TCombobox",
              fieldbackground=[("readonly", CARD)],
              bordercolor=[("focus", PRIMARY), ("hover", BORDER_STRONG)],
              arrowcolor=[("hover", PRIMARY)])
    root.option_add("*TCombobox*Listbox.background", CARD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", PRIMARY)
    root.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")
    root.option_add("*TCombobox*Listbox.font", font(10))
    root.option_add("*TCombobox*Listbox.borderWidth", 0)

    # 左右分栏的分隔条
    style.configure("TSeparator", background=BORDER)
