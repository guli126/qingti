"""左侧场景树。

结构跟常见 Agent 界面一样：

    ▾ 编程                    +
        记账工具小助手
        周报模板改写
    ▸ 办公                    +
    ▾ 图像                    +
        封面图

点场景标题 = 折叠/展开（同时把它设为当前场景）；点 + = 在该场景下新建任务；
点任务 = 切过去；任务行右侧的 ⋯ 可以重命名或删除。
"""

import tkinter as tk
from tkinter import messagebox, simpledialog

from core import engine, sessions

from . import theme as T
from .widgets import Button

class _Arrow(tk.Canvas):
    """折叠箭头。

    不用 ▾ 字符：雅黑里这个字形又小又轻，缩到 8pt 就成一个点了。
    直接画三角形，缩放到什么字号都清晰。
    """

    def __init__(self, master, open_=True, color="#69737F", bg=T.SIDEBAR):
        super().__init__(master, width=16, height=16, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._color = color
        self._open = bool(open_)
        self._draw()

    def _draw(self):
        self.delete("all")
        if self._open:                      # 展开：朝下
            pts = [3.5, 6, 12.5, 6, 8, 11.5]
        else:                               # 收起：朝右
            pts = [6, 3.5, 11.5, 8, 6, 12.5]
        self.create_polygon(pts, fill=self._color, outline="")

    def set_open(self, value: bool):
        self._open = bool(value)
        self._draw()

    def set_color(self, color: str):
        self._color = color
        self._draw()


class SceneTree(tk.Frame):
    def __init__(self, master, on_pick, on_new, on_toggle_group, on_changed=None):
        super().__init__(master, bg=T.SIDEBAR)
        self._on_pick = on_pick
        self._on_new = on_new
        self._on_toggle_group = on_toggle_group
        self._on_changed = on_changed
        self._groups = {}
        self.refresh()

    def refresh(self, keep_scroll=False):
        data = sessions.load()
        active = data.get("active") or ""
        for w in self.winfo_children():
            w.destroy()
        self._groups = {}
        for key in ("coding", "work", "image"):
            group = _SceneGroup(
                self, key, engine.SCENES[key]["name"],
                collapsed=sessions.collapsed(key, data),
                tasks=sessions.by_scene(key, data),
                active=active,
                on_toggle=self._toggle,
                on_add=self._add,
                on_pick=self._on_pick,
                on_menu=self._menu,
            )
            group.pack(fill="x", padx=8, pady=(7, 0))
            self._groups[key] = group

    def set_active(self, task_id: str):
        for g in self._groups.values():
            g.set_active(task_id)

    def expand(self, scene: str):
        g = self._groups.get(scene)
        if g and g.is_collapsed():
            g.set_collapsed(False)

    def _toggle(self, scene: str):
        g = self._groups.get(scene)
        if not g:
            return
        now = not g.is_collapsed()
        g.set_collapsed(now)
        sessions.set_collapsed(scene, now)
        if self._on_toggle_group:
            self._on_toggle_group(scene, now)

    def _add(self, scene: str):
        if self._on_new:
            self._on_new(scene)

    def _menu(self, task_id: str, x: int, y: int):
        task = sessions.get(task_id)
        if not task:
            return
        menu = tk.Menu(self, tearoff=0, bg=T.CARD, fg=T.TEXT,
                       activebackground=T.PRIMARY, activeforeground="#FFFFFF",
                       bd=0, font=T.font(10))
        menu.add_command(label="重命名",
                         command=lambda: self._rename(task_id, task))
        menu.add_separator()
        menu.add_command(label="删除",
                         command=lambda: self._delete(task_id, task))
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _rename(self, task_id: str, task: dict):
        new = simpledialog.askstring(
            "重命名", "给这个任务起个名字：", parent=self,
            initialvalue=task.get("title") or "")
        if new is None:
            return
        sessions.rename(task_id, new)
        self._after_change()

    def _delete(self, task_id: str, task: dict):
        if not messagebox.askyesno(
                "删除任务",
                "确定删除「%s」吗？\n对话内容会一起删掉，无法恢复。"
                % (task.get("title") or "未命名"), parent=self):
            return
        sessions.remove(task_id)
        self._after_change()

    def _after_change(self):
        """改完等一拍再重建：触发这次改动的菜单/控件还在回调栈上。"""
        def go():
            self.refresh()
            if self._on_changed:
                self._on_changed()
        self.after(10, go)


# ------------------------------------------------------------------ 分组


class _SceneGroup(tk.Frame):
    def __init__(self, master, key, name, collapsed, tasks, active,
                 on_toggle, on_add, on_pick, on_menu):
        super().__init__(master, bg=T.SIDEBAR)
        self._key = key
        self._collapsed = bool(collapsed)
        self._on_toggle = on_toggle
        self._on_add = on_add

        # 标题行
        head = tk.Frame(self, bg=T.SIDEBAR, cursor="hand2")
        head.pack(fill="x")

        self._arrow = _Arrow(head, open_=not collapsed)
        self._arrow.pack(side="left", padx=(0, 6), pady=7)

        self._title = tk.Label(head, text=name, bg=T.SIDEBAR, fg="#8994A4",
                               font=T.font(10, True), anchor="w", cursor="hand2")
        self._title.pack(side="left", fill="x", expand=True)

        # 「+」常驻（灰一点），悬停才变亮——藏起来新手根本找不到
        self._add = tk.Label(head, text="+", bg=T.SIDEBAR, fg="#5E6878",
                             font=T.font(12), width=2, cursor="hand2")
        self._add.pack(side="right", pady=(1, 0))

        for w in (head, self._arrow, self._title):
            w.bind("<Button-1>", self._toggle)
        for w in (head, self._arrow, self._title, self._add):
            w.bind("<Enter>", self._hover_on)
            w.bind("<Leave>", self._hover_off)
        self._add.bind("<Button-1>", self._add_task)

        # 任务列表
        self._body = tk.Frame(self, bg=T.SIDEBAR)
        self._items = []
        for t in tasks:
            item = _TaskItem(self._body, t, active=(t.get("id") == active),
                             on_pick=on_pick, on_menu=on_menu)
            item.pack(fill="x", padx=(22, 0))
            self._items.append(item)
        if not collapsed:
            self._body.pack(fill="x", pady=(1, 4))

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, value: bool):
        self._collapsed = bool(value)
        self._arrow.set_open(not value)
        if value:
            self._body.pack_forget()
        else:
            self._body.pack(fill="x", pady=(1, 4))

    def set_active(self, task_id: str):
        for item in self._items:
            item.set_active(item.task_id == task_id)

    def _toggle(self, _=None):
        if self._on_toggle:
            self._on_toggle(self._key)

    def _hover_on(self, _=None):
        self._title.configure(fg="#FFFFFF")
        self._arrow.set_color("#9AA5B6")
        self._add.configure(fg="#FFFFFF")

    def _hover_off(self, _=None):
        self._title.configure(fg="#8994A4")
        self._arrow.set_color("#69737F")
        self._add.configure(fg="#5E6878")

    def _add_task(self, _=None):
        if self._on_add:
            self._on_add(self._key)


# ------------------------------------------------------------------ 任务项


class _TaskItem(tk.Frame):
    def __init__(self, master, task, active, on_pick, on_menu):
        super().__init__(master, bg=T.SIDEBAR, cursor="hand2")
        self.task_id = task.get("id") or ""
        self._active = bool(active)
        self._on_pick = on_pick
        self._on_menu = on_menu

        # 选中态左侧的竖条
        self._bar = tk.Frame(self, bg=T.SIDEBAR, width=2)
        self._bar.pack(side="left", fill="y")

        self._label = tk.Label(self, text=task.get("title") or "未命名",
                               bg=T.SIDEBAR,
                               fg=T.SIDEBAR_TEXT_ON if active else "#B6BFCC",
                               font=T.font(10), anchor="w", cursor="hand2",
                               padx=8, pady=5)
        self._label.pack(side="left", fill="x", expand=True)

        self._more = tk.Label(self, text="⋯", bg=T.SIDEBAR, fg="#7B8595",
                              font=T.font(11), width=2, cursor="hand2")
        self._more.pack_forget()

        for w in (self, self._label):
            w.bind("<Button-1>", self._pick)
            w.bind("<Button-3>", self._show_menu)
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)
        self._more.bind("<Button-1>", self._show_menu)

        self._paint()

    def _paint(self):
        bg = T.SIDEBAR_HOVER if self._active else T.SIDEBAR
        self.configure(bg=bg)
        self._label.configure(bg=bg, fg=T.SIDEBAR_TEXT_ON if self._active
                              else "#B6BFCC")
        self._bar.configure(bg=T.SIDEBAR_ACTIVE if self._active else bg)
        self._more.configure(bg=bg)

    def set_active(self, on: bool):
        self._active = bool(on)
        self._paint()

    def _pick(self, _=None):
        if self._on_pick:
            self._on_pick(self.task_id)

    def _enter(self, _=None):
        if not self._active:
            self.configure(bg=T.SIDEBAR_HOVER)
            self._label.configure(bg=T.SIDEBAR_HOVER)
            self._more.configure(bg=T.SIDEBAR_HOVER)
            self._bar.configure(bg=T.SIDEBAR_HOVER)
        self._more.pack(side="right", padx=(0, 4))

    def _leave(self, _=None):
        self._more.pack_forget()
        self._paint()

    def _show_menu(self, event):
        if self._on_menu:
            self._on_menu(self.task_id, event.x_root, event.y_root)
        return "break"
