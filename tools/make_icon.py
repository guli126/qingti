"""生成 app.ico：蓝色圆角底 + 白色对话气泡 + 对勾。

纯标准库（zlib + struct），不依赖 Pillow。
形状用 4 倍超采样再缩，得到平滑边缘。
"""

import math
import os
import struct
import zlib

BLUE = (47, 111, 237)
SIZES = (256, 128, 64, 48, 32, 16)


def _dist_seg(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    den = dx * dx + dy * dy
    t = 0.0 if den == 0 else ((px - ax) * dx + (py - ay) * dy) / den
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _in_rrect(u, v, x0, y0, x1, y1, r):
    if u < x0 or u > x1 or v < y0 or v > y1:
        return False
    cx = min(max(u, x0 + r), x1 - r)
    cy = min(max(v, y0 + r), y1 - r)
    return (u - cx) ** 2 + (v - cy) ** 2 <= r * r


def _pixel(u, v):
    """返回 (r,g,b,a)；u,v ∈ [0,1]。"""
    # 背景：圆角方形
    if not _in_rrect(u, v, 0.03, 0.03, 0.97, 0.97, 0.23):
        return (0, 0, 0, 0)

    # 气泡主体
    bubble = _in_rrect(u, v, 0.15, 0.17, 0.85, 0.63, 0.13)
    # 气泡尾巴（左下角小三角）
    tail = False
    if 0.24 <= u <= 0.40 and 0.58 <= v <= 0.79:
        # 斜边：从 (0.24,0.63) 到 (0.40,0.58) 下方收敛到 (0.28,0.79)
        left = 0.24 + (v - 0.63) * 0.18
        right = 0.40 - (v - 0.58) * 0.62
        tail = left <= u <= max(left, right)

    if bubble or tail:
        # 气泡里画对勾（蓝色）
        d = min(_dist_seg(u, v, 0.29, 0.40, 0.44, 0.53),
                _dist_seg(u, v, 0.44, 0.53, 0.71, 0.27))
        if d <= 0.055:
            return BLUE + (255,)
        return (255, 255, 255, 255)

    return BLUE + (255,)


def render(size, ss=4):
    """超采样渲染，返回 RGBA 字节流。"""
    n = size * ss
    acc = [[[0.0] * 4 for _ in range(size)] for _ in range(size)]
    for py in range(n):
        v = (py + 0.5) / n
        row = []
        for px in range(n):
            u = (px + 0.5) / n
            row.append(_pixel(u, v))
        ty = py // ss
        for px, c in enumerate(row):
            tgt = acc[ty][px // ss]
            a = c[3] / 255.0
            for i in range(3):
                tgt[i] += c[i] * a
            tgt[3] += a

    out = bytearray()
    per = ss * ss
    for y in range(size):
        out.append(0)  # filter type 0
        for x in range(size):
            r, g, b, a = acc[y][x]
            alpha = a / per
            if alpha <= 0.001:
                out += bytes(4)
            else:
                out.append(min(255, int(round(r / a))))
                out.append(min(255, int(round(g / a))))
                out.append(min(255, int(round(b / a))))
                out.append(min(255, int(round(alpha * 255))))
    return bytes(out)


def png_bytes(size):
    raw = render(size)
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def build(path):
    images = [(s, png_bytes(s)) for s in SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, data in images:
        w = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32,
                               len(data), offset)
        blobs += data
        offset += len(data)
    with open(path, "wb") as f:
        f.write(header + entries + blobs)
    return os.path.getsize(path)


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    target = os.path.join(here, "app.ico")
    n = build(target)
    print("wrote %s (%d bytes, %d sizes)" % (target, n, len(SIZES)))
