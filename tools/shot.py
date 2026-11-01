"""窗口截图（纯标准库）。

用 GDI 的 BitBlt 抓屏幕区域，再手写 PNG。没有 Pillow 也能用。
只用于开发时看效果，不参与打包。
"""

import ctypes
import struct
import zlib
from ctypes import wintypes

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


class _BMIH(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD),
                ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def grab(x, y, w, h):
    """抓屏幕一块区域，返回 (w, h, 每行 RGB 字节串)。"""
    hdc = user32.GetDC(0)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    gdi32.BitBlt(mdc, 0, 0, w, h, hdc, x, y, 0x00CC0020)   # SRCCOPY

    bi = _BMIH()
    bi.biSize = ctypes.sizeof(_BMIH)
    bi.biWidth = w
    bi.biHeight = -h        # 负值 = 自上而下，省一次翻转
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0    # BI_RGB

    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(0, hdc)
    return w, h, buf.raw


class _RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


def _dib(mdc, bmp, w, h):
    """从内存 DC 里那块位图取像素（BGRA），返回 (w, h, bytes)。

    位图句柄要显式传进来：GetCurrentObject(mdc, 0) 取的是「当前画笔」而不是
    位图（OBJ_BITMAP 是 7），拿错句柄 GetDIBits 会静默失败，最后得到一张白图。
    """
    bi = _BMIH()
    bi.biSize = ctypes.sizeof(_BMIH)
    bi.biWidth = w
    bi.biHeight = -h
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    return w, h, buf.raw


def save_window(hwnd, path, via="screen"):
    """抓某个窗口的画面。

    via="screen"（默认）：从屏幕对应矩形位块拷贝。窗口必须在最前面，但抓到的
    就是真实画面——tkinter 窗口只能这么抓。
    via="print"：PrintWindow 让窗口自己重绘到内存 DC。对 tkinter 无效，它会
    "成功"返回一张纯白图，别指望它。
    """
    rc = _RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rc))
    w = rc.right - rc.left
    h = rc.bottom - rc.top
    if w <= 0 or h <= 0:
        raise ValueError("窗口尺寸无效：%dx%d" % (w, h))

    screen = user32.GetDC(0)
    mdc = gdi32.CreateCompatibleDC(screen)
    bmp = gdi32.CreateCompatibleBitmap(screen, w, h)
    gdi32.SelectObject(mdc, bmp)

    if via == "print":
        ok = bool(user32.PrintWindow(hwnd, mdc, 0))
    else:
        ok = bool(gdi32.BitBlt(mdc, 0, 0, w, h, screen, rc.left, rc.top,
                               0x00CC0020))

    w2, h2, data = _dib(mdc, bmp, w, h)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(0, screen)

    _write_png(path, w2, h2, data)
    return path, ok


def _png(w, h, rgb_lines):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)   # 8bit truecolor
    body = b"".join(b"\x00" + line for line in rgb_lines)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(body, 6)) + chunk(b"IEND", b""))


def _write_png(path, w, h, data):
    stride = w * 4
    lines = []
    for row in range(h):
        base = row * stride
        seg = data[base:base + stride]
        r = seg[2::4]
        g = seg[1::4]
        b = seg[0::4]
        inter = bytearray(w * 3)
        inter[0::3] = r
        inter[1::3] = g
        inter[2::3] = b
        lines.append(bytes(inter))
    with open(path, "wb") as f:
        f.write(_png(w, h, lines))


def save(path, x, y, w, h):
    w, h, data = grab(x, y, w, h)
    stride = w * 4
    lines = []
    for row in range(h):
        base = row * stride
        seg = data[base:base + stride]
        # 内存里是 BGRA，PNG 要 RGB
        r = seg[2::4]
        g = seg[1::4]
        b = seg[0::4]
        inter = bytearray(w * 3)
        inter[0::3] = r
        inter[1::3] = g
        inter[2::3] = b
        lines.append(bytes(inter))
    with open(path, "wb") as f:
        f.write(_png(w, h, lines))
    return path


def save_widget(widget, path):
    """截一个 tk 控件（含边框）自己的区域。"""
    widget.update_idletasks()
    x = widget.winfo_rootx()
    y = widget.winfo_rooty()
    w = widget.winfo_width()
    h = widget.winfo_height()
    return save(path, x, y, w, h)
