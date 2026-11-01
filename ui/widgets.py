"""自绘组件库。

tk 原生控件的样式太旧：圆角做不到、勾选框跟文字对不齐、按钮有立体边框。
这里用 Canvas 画几个基础件，界面只拼这些，观感才统一。

所有组件都遵守两个约定：
  1. 颜色一律从 theme 取，不硬编码
  2. 文字和图标用同一个 margin 盒子排版，天然水平对齐
"""

import math
import tkinter as tk
from tkinter import ttk

from . import theme as T


# ------------------------------------------------------------------ 圆角路径


def rr_points(x0, y0, x1, y1, r, steps=8):
    """圆角矩形的采样点。用精确描点而不是 smooth 近似，圆角才不会变形。"""
    r = max(0.0, min(r, (x1 - x0) / 2.0, (y1 - y0) / 2.0))
    if r <= 0:
        return [x0, y0, x1, y0, x1, y1, x0, y1]
    pts = []
    for cx, cy, a0, a1 in ((x1 - r, y0 + r, -90, 0),
                           (x1 - r, y1 - r, 0, 90),
                           (x0 + r, y1 - r, 90, 180),
                           (x0 + r, y0 + r, 180, 270)):
        for i in range(steps + 1):
            a = math.radians(a0 + (a1 - a0) * i / steps)
            pts.extend([cx + r * math.cos(a), cy + r * math.sin(a)])
    return pts


def draw_round(canvas, x0, y0, x1, y1, r, fill, outline="", width=1, tags=""):
    return canvas.create_polygon(
        rr_points(x0, y0, x1, y1, r), fill=fill, outline=outline,
        width=width, tags=tags, joinstyle="round")


# ------------------------------------------------------------------ 按钮

_BTN_STYLES = {
    #            底色        文字        悬停底      按下底      边框
    "primary": (T.PRIMARY, "#FFFFFF", T.PRIMARY_HOVER, "#1E4CB0", ""),
    "ghost":   (T.CARD, T.TEXT, T.PRIMARY_SOFT, T.PRIMARY_SOFT, T.BORDER_STRONG),
    "soft":    (T.PRIMARY_SOFT, T.PRIMARY, "#DCE8FD", "#CFDDFB", ""),
    "danger":  (T.CARD, T.ERR, T.ERR_SOFT, "#FAD9D9", T.BORDER_STRONG),
    # 悬停用中性灰而不是淡蓝：淡蓝跟「选中」长得太像，鼠标一划过去
    # 会让人以为已经切过去了
    "plain":   (None, T.TEXT_SUB, "#EAECF0", "#E1E4EA", ""),
    # 深色侧栏上用：底色透明、文字浅灰、悬停微微提亮
    "nav":     (None, T.SIDEBAR_TEXT, T.SIDEBAR_HOVER, "#333E50", ""),
}


class Button(tk.Canvas):
    """圆角按钮。宽度按文字实际像素算，中英文混排不会错位。"""

    def __init__(self, master, text, command=None, kind="primary", size=10,
                 bold=False, padx=16, pady=7, width=None, radius=None,
                 parent_bg=None, align="center"):
        bg = parent_bg or _bg_of(master)
        normal, fg, hover, press, border = _BTN_STYLES[kind]
        if normal is None:
            normal = bg

        f = T.font(size, bold)
        tw = f.measure(text)
        th = f.metrics("linespace")
        # 注意：不能用 _w / _h 命名——tkinter 内部用 self._w 存控件路径名，
        # 覆盖它会让后面所有 Tk 调用拿到一个字符串而炸掉。
        self._own_w = width or (tw + padx * 2)
        self._own_h = th + pady * 2
        self._radius = T.RADIUS - 2 if radius is None else radius

        super().__init__(master, width=self._own_w, height=self._own_h,
                         bg=bg, highlightthickness=0, bd=0)
        self._colors = (normal, fg, hover, press, border)
        self._text = text
        self._font = f
        self._size = size
        self._command = command
        self._enabled = True
        self._bg = bg
        self._hover = False

        self._shape = draw_round(self, 0.5, 0.5, self._own_w - 0.5,
                                 self._own_h - 0.5, self._radius,
                                 normal, border)
        # Canvas 没有 widget 级 anchor，文字对齐只能靠 create_text 的 anchor
        if align == "left":
            tx, ta = padx, "w"
        elif align == "right":
            tx, ta = self._own_w - padx, "e"
        else:
            tx, ta = self._own_w / 2, "center"
        self._label = self.create_text(tx, self._own_h / 2, text=text,
                                       fill=fg, font=f, anchor=ta)
        self.configure(cursor="hand2")
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    # -- 状态
    def set_enabled(self, on: bool):
        self._enabled = bool(on)
        self.configure(cursor="hand2" if on else "arrow")
        self.itemconfigure(self._label, fill=self._colors[1] if on else T.MUTED)
        self._paint(self._colors[0] if on else self._bg)

    def set_text(self, text: str):
        self._text = text
        self.itemconfigure(self._label, text=text)

    def set_command(self, command):
        """切换按钮要接的业务动作，按键位复用同一个控件时用得上。"""
        self._command = command

    def set_bold(self, on: bool):
        """只换字体粗细，不动底色——选中态靠「软底 + 粗体」双保险。"""
        self._font = T.font(self._size, bool(on))
        self.itemconfigure(self._label, font=self._font)

    def set_kind(self, kind: str):
        normal, fg, hover, press, border = _BTN_STYLES[kind]
        if normal is None:
            normal = self._bg
        self._colors = (normal, fg, hover, press, border)
        self.itemconfigure(self._label, fill=fg)
        self._paint(normal)

    def _paint(self, color, border=None):
        self.itemconfigure(self._shape, fill=color)
        b = self._colors[4] if border is None else border
        self.itemconfigure(self._shape, outline=b or color)

    # -- 事件
    def _on_enter(self, _=None):
        if self._enabled:
            self._hover = True
            self._paint(self._colors[2])

    def _on_leave(self, _=None):
        self._hover = False
        if self._enabled:
            self._paint(self._colors[0])

    def _on_press(self, _=None):
        if self._enabled:
            self._paint(self._colors[3])

    def _on_release(self, _=None):
        if not self._enabled:
            return
        self._paint(self._colors[2] if self._hover else self._colors[0])
        if self._command:
            self._command()


def _bg_of(widget) -> str:
    """往上找第一个能取到背景色的控件，用作自绘件的底色。"""
    w = widget
    for _ in range(6):
        try:
            c = w.cget("bg")
            if c:
                return str(c)
        except Exception:
            pass
        w = getattr(w, "master", None)
        if w is None:
            break
    return T.BG


# ------------------------------------------------------------------ 开关


class Toggle(tk.Frame):
    """开关 + 标签，横向排版。

    原生 Checkbutton 的方框和文字基线对不齐（这是 Windows Tk 的老问题），
    所以这里自绘：文字和轨道都用同一套 pady，永远在同一条水平中线上。
    """

    def __init__(self, master, text, value=False, command=None,
                 bg=None, width=40, height=22):
        bg = bg or _bg_of(master)
        super().__init__(master, bg=bg)
        self._value = bool(value)
        self._command = command
        self._track_w = width
        self._track_h = height
        self._on_color = T.PRIMARY
        self._off_color = T.BORDER_STRONG
        self._bg = bg

        self._canvas = tk.Canvas(self, width=width, height=height, bg=bg,
                                 highlightthickness=0, bd=0, cursor="hand2")
        self._canvas.pack(side="left")

        self._track = draw_round(self._canvas, 1, 1, width - 1, height - 1,
                                 height / 2 - 1,
                                 self._on_color if value else self._off_color)
        knob = height - 6
        self._knob_r = knob / 2
        self._knob = self._canvas.create_oval(0, 0, 0, 0, fill="#FFFFFF",
                                              outline="")
        self._place_knob()

        self._label = tk.Label(self, text=text, bg=bg, fg=T.TEXT,
                               font=T.font(10), cursor="hand2")
        # 左右都用 8px 间距，垂直居中由 pack 自动完成
        self._label.pack(side="left", padx=(8, 0), pady=0)

        for w in (self._canvas, self._label):
            w.bind("<Button-1>", self._toggle)

    def _place_knob(self):
        h = self._track_h
        knob = h - 6
        x = (self._track_w - knob - 3) if self._value else 3
        self._canvas.coords(self._knob, x, 3, x + knob, 3 + knob)

    def _toggle(self, _=None):
        self._value = not self._value
        self._canvas.itemconfigure(
            self._track, fill=self._on_color if self._value else self._off_color)
        self._place_knob()
        if self._command:
            self._command(self._value)

    def get(self) -> bool:
        return self._value

    def set(self, v: bool):
        if bool(v) != self._value:
            self._toggle()


# ------------------------------------------------------------------ 卡片


class RoundCard(tk.Canvas):
    """圆角卡片。高度随内容自动伸缩，宽度跟随父容器。

    用法：往 card.body 里 pack 内容即可，不用管尺寸。
    """

    def __init__(self, master, bg=T.CARD, border=T.BORDER, radius=12,
                 paddingx=16, paddingy=14, parent_bg=None, border_width=1,
                 width=None):
        pbg = parent_bg or _bg_of(master)
        kw = {"width": width} if width else {}
        super().__init__(master, bg=pbg, highlightthickness=0, bd=0,
                         height=10, **kw)
        self._bg = bg
        self._border = border
        self._bw = border_width
        self._radius = radius
        self._px = paddingx
        self._py = paddingy
        self._shape = None

        self.body = tk.Frame(self, bg=bg)
        self._win = self.create_window(self._px, self._py,
                                       window=self.body, anchor="nw")
        self.bind("<Configure>", self._on_resize)
        # 注意：Canvas 里嵌的 Frame 收不到 <Configure>（它的实际尺寸被 Canvas
        # 接管了，reqheight 变化不会触发事件）。所以只能主动轮询。
        self._last_req = -1
        self._poll_height()

    def set_border(self, color: str, width: int | None = None):
        """只改边框颜色，用于选中态高亮。"""
        self._border = color
        if width is not None:
            self._bw = width
        self._redraw(self.winfo_width(), self.winfo_height())

    def _on_resize(self, event):
        self.itemconfigure(self._win, width=max(1, event.width - self._px * 2))
        self._redraw(event.width, event.height)

    def _poll_height(self):
        """内容变了就把画布撑到内容高度。"""
        try:
            need = self.body.winfo_reqheight() + self._py * 2
            if need != self._last_req and need > 2:
                self._last_req = need
                self.configure(height=need)
                w = self.winfo_width()
                if w > 4:
                    self._redraw(w, need)
        except tk.TclError:
            return                      # 控件已销毁，停掉轮询
        self.after(25, self._poll_height)

    def _redraw(self, w, h):
        if w < 4 or h < 4:
            return
        if self._shape is not None:
            self.delete(self._shape)
        self._shape = draw_round(self, self._bw / 2, self._bw / 2,
                                 w - self._bw / 2, h - self._bw / 2,
                                 self._radius, self._bg,
                                 self._border if self._bw else "",
                                 self._bw)
        self.tag_lower(self._shape)


# ------------------------------------------------------------------ 滚动区


class ScrollFrame(tk.Frame):
    """竖向滚动容器，往 .inner 里放东西。"""

    def __init__(self, master, bg=T.BG, padding=(0, 0), right_gap=0,
                 sb_style="Slim.Vertical.TScrollbar"):
        super().__init__(master, bg=bg)
        self._gap = right_gap
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical",
                                 command=self.canvas.yview,
                                 style=sb_style)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window(
            (padding[0], padding[1]), window=self.inner, anchor="nw")

        self._pad = padding
        self.inner.bind("<Configure>", self._sync_region)
        self.canvas.bind("<Configure>", self._sync_width)
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)

    def _sync_region(self, _=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _sync_width(self, event):
        self.canvas.itemconfigure(
            self._win,
            width=max(1, event.width - self._pad[0] * 2 - self._gap))

    def _bind_wheel(self, _=None):
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)

    def _unbind_wheel(self, _=None):
        self.canvas.unbind_all("<MouseWheel>")

    def _on_wheel(self, event):
        if self.inner.winfo_reqheight() <= self.canvas.winfo_height():
            return
        self.canvas.yview_scroll(int(-event.delta / 120) * 3, "units")

    def to_bottom(self):
        """滚到底。

        卡片高度是延迟撑开的（RoundCard 靠轮询同步），所以滚两次：
        立刻一次，再等 160ms 一次，保证内容真正布局完还能停在底部。
        """
        def go():
            try:
                bbox = self.canvas.bbox("all")
                if bbox:
                    self.canvas.configure(scrollregion=bbox)
                # 内容还没占满一屏就顶到最上面，否则滚到底
                fits = (self.inner.winfo_reqheight()
                        <= self.canvas.winfo_height() + 2)
                self.canvas.yview_moveto(0.0 if fits else 1.0)
            except tk.TclError:
                pass

        try:
            self.canvas.update_idletasks()
        except tk.TclError:
            return
        go()
        self.after(160, go)

    def clear(self):
        for w in self.inner.winfo_children():
            w.destroy()


# ------------------------------------------------------------------ 文本


def make_entry(master, textvariable=None, width=20, show=None, bg=T.CARD):
    return tk.Entry(master, textvariable=textvariable, width=width,
                    relief="flat", bd=0, bg=bg, fg=T.TEXT,
                    insertbackground=T.TEXT, font=T.font(10),
                    highlightthickness=1,
                    highlightbackground=T.BORDER_STRONG,
                    highlightcolor=T.PRIMARY, show=show or "")


def make_text(master, height=4, bg=T.CARD, font=None, wrap="word"):
    return tk.Text(master, height=height, relief="flat", bd=0, bg=bg,
                   fg=T.TEXT, insertbackground=T.TEXT,
                   font=font or T.font(10), wrap=wrap,
                   highlightthickness=1,
                   highlightbackground=T.BORDER_STRONG,
                   highlightcolor=T.PRIMARY,
                   padx=10, pady=8, spacing1=2, spacing3=3)


def render_markdown(widget: tk.Text, text: str) -> None:
    """把常见 Markdown 标记映射成 Text 的 tag。

    不追求完整语法，只处理真正影响阅读的几种：标题、粗体、行内代码、列表。
    """
    widget.configure(state="normal")
    widget.delete("1.0", "end")

    widget.tag_configure("h1", font=T.font(12, True), spacing1=8, spacing3=6)
    widget.tag_configure("h2", font=T.font(11, True), spacing1=8, spacing3=4)
    widget.tag_configure("h3", font=T.font(10, True), spacing1=6, spacing3=3)
    widget.tag_configure("bold", font=T.font(10, True))
    widget.tag_configure("code", font=T.font(9, mono=True),
                         background="#F1F3F6", foreground="#B5335A")
    widget.tag_configure("bullet", lmargin1=6, lmargin2=18)
    widget.tag_configure("quote", foreground=T.TEXT_SUB, lmargin1=12,
                         lmargin2=12)

    for line in (text or "").split("\n"):
        stripped = line.strip()
        if stripped.startswith("### "):
            _emit(widget, stripped[4:], ("h3",), wrap_line=True)
        elif stripped.startswith("## "):
            _emit(widget, stripped[3:], ("h2",), wrap_line=True)
        elif stripped.startswith("# "):
            _emit(widget, stripped[2:], ("h1",), wrap_line=True)
        elif stripped.startswith(("- ", "* ", "· ")):
            _emit(widget, "• " + stripped[2:], ("bullet",), wrap_line=True)
        elif stripped.startswith("> "):
            _emit(widget, stripped[2:], ("quote",), wrap_line=True)
        else:
            _emit(widget, line, (), wrap_line=True)

    widget.configure(state="disabled")


def _emit(widget: tk.Text, line: str, base_tags: tuple, wrap_line=False) -> None:
    """按 **粗体** 和 `代码` 切分后插入。"""
    import re
    pos = 0
    pattern = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`")
    for m in pattern.finditer(line):
        if m.start() > pos:
            widget.insert("end", line[pos:m.start()], base_tags)
        if m.group(1) is not None:
            widget.insert("end", m.group(1), base_tags + ("bold",))
        else:
            widget.insert("end", m.group(2), base_tags + ("code",))
        pos = m.end()
    if pos < len(line):
        widget.insert("end", line[pos:], base_tags)
    if wrap_line:
        widget.insert("end", "\n", base_tags)


def hline(master, color=None, pady=0):
    f = tk.Frame(master, height=1, bg=color or T.BORDER)
    f.pack(fill="x", pady=pady)
    return f


def wrap_to(container, label, reserve=90):
    """让 label 的换行宽度跟着容器走。

    大窗口下固定 wraplength 会把文字挤成窄窄一条，窗口拉小时又会溢出。
    """
    def on_configure(event):
        try:
            label.configure(wraplength=max(240, event.width - reserve))
        except tk.TclError:
            pass
    container.bind("<Configure>", on_configure, add="+")
