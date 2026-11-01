# -*- coding: utf-8 -*-
"""轻提宣传片生成器 v2（一次性工具，不进仓库、不参与打包）。

相比 v1 的三点改动：
  1. 配音换成 edge-tts 神经语音（zh-CN-XiaoxiaoNeural），不再是 SAPI 的机器味；
  2. 彻底不用 ffmpeg 的 zoompan，改由 Pillow 逐帧渲染后管进编码器，
     镜头不再逐帧抖动；
  3. 每个元素都有入场动画（位移 + 淡入 + 回弹），底部常驻进度条，
     第 4 段有鼠标点击演示。

用法：
    python tools/make_video.py            # 横版 + 竖版
    python tools/make_video.py v          # 只出竖版
    python tools/make_video.py cover      # 只出封面
"""

import asyncio
import io
import math
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VID = os.path.join(ROOT, "video")
SHOTS = os.path.join(VID, "shots")
TTS = os.path.join(VID, "tts")
OUT = os.path.join(VID, "out")
FF = ("C:/Users/Administrator/AppData/Local/Programs/Python/Python310/"
      "lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe")

F_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
F_REG = "C:/Windows/Fonts/msyh.ttc"

VOICE = "zh-CN-XiaoxiaoNeural"
VOICE_RATE = "+12%"

INK = (10, 14, 24)
INK2 = (20, 27, 44)
ACCENT = (47, 111, 237)
ACCENT_SOFT = (126, 170, 255)
WHITE = (247, 249, 252)
SUB = (162, 175, 194)
DARK_CARD = (30, 39, 58)
GOLD = (255, 214, 102)

FPS = 30
LEAD = 0.45
TAIL = 0.60
XF = 0.60

AR = 1.596
AR_EDITOR = 1.474

# 每个元素统一用“出现时刻 + 时长”来驱动
NOTICE_LINES = [
    "由于本人懒得进行视频的制作与录音，",
    "故本视频 100% 由 AI 生成；",
    "软件完全开源，下载链接放在简介或评论区。",
]

SCENES = [
    dict(key="notice", lines=[], fixed=4.6),
    dict(key="hook", lines=[
        "同一句话，交给两个 AI。",
        "能问出十种结果。",
        "不是 AI 笨，是你没把话说清楚。",
    ]),
    dict(key="pain", lines=[
        "难的不是措辞。",
        "是你根本不知道自己漏了什么。",
        "用在哪、给谁看、什么算做完。",
    ]),
    dict(key="intro", lines=[
        "轻提，本地的提示词优化器。",
        "你说一句大白话，它先反问你。",
    ]),
    dict(key="ask", lines=[
        "问题都是选择题，能点的不用打字。",
        "每题都标好了推荐项。",
        "懒得答，就点一下「就这些，开始吧」。",
    ]),
    dict(key="result", lines=[
        "几秒后，你拿到分好节的提示词。",
        "目标、场景、约束、验收标准。",
        "复制就能用。",
    ]),
    dict(key="modes", lines=[
        "编程、办公、图像，三个场景，十三套模板。",
        "模板就是 Markdown，改完保存立刻生效。",
    ]),
    dict(key="outro", lines=[
        "全部在本机跑，不联网上传。",
        "MIT 开源，绿色版双击就用。",
        "地址放在评论区。",
    ]),
]

BEAT_GAP = 0.0      # 节拍之间无间隙，靠淡入区分
SCENE_TAIL = 0.55   # 每段尾部留白
# ------------------------------------------------------------------ 工具
def font(size, bold=False):
    return ImageFont.truetype(F_BOLD if bold else F_REG, max(8, int(size)))


def ease_out(t):
    return 1 - (1 - t) ** 3


def ease_out_back(t):
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def clamp01(x):
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def anim(t, start, dur=0.55):
    """返回 0→1 的缓动进度。"""
    return ease_out(clamp01((t - start) / dur))


def rgba(color, alpha):
    if len(color) == 4:
        color = color[:3]
    return (color[0], color[1], color[2], int(255 * clamp01(alpha)))


def fit_font(draw, s, maxw, size, bold=True):
    f = font(size, bold)
    while draw.textlength(s, font=f) > maxw and size > 12:
        size -= 2
        f = font(size, bold)
    return f


def make_bg(w, h):
    strip = Image.new("RGB", (1, h))
    px = strip.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = (int(INK[0] + (INK2[0] - INK[0]) * t),
                    int(INK[1] + (INK2[1] - INK[1]) * t),
                    int(INK[2] + (INK2[2] - INK[2]) * t))
    base = strip.resize((w, h), Image.BILINEAR)

    glow = Image.new("RGB", (w, h), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    r1 = int(w * 0.42)
    gd.ellipse([w * 0.54 - r1, -r1 * 0.72, w * 0.54 + r1, r1 * 0.95],
               fill=(26, 52, 110))
    r2 = int(w * 0.30)
    gd.ellipse([-r2 * 0.6, h * 0.62 - r2, r2 * 1.4, h * 0.62 + r2],
               fill=(14, 30, 68))
    glow = glow.filter(ImageFilter.GaussianBlur(int(w * 0.055)))
    return Image.blend(base, glow, 0.55).convert("RGBA")


_BG_CACHE = {}


def bg_for(size):
    if size not in _BG_CACHE:
        _BG_CACHE[size] = make_bg(*size)
    return _BG_CACHE[size].copy()


def card_layer(shot_path, width, radius=20):
    """把截图做成带投影的 RGBA 卡片。"""
    shot = Image.open(shot_path).convert("RGB")
    h = int(width / (shot.width / shot.height))
    shot = shot.resize((width, h), Image.LANCZOS)

    pad = int(width * 0.05)
    canvas = Image.new("RGBA", (width + pad * 2, h + pad * 2), (0, 0, 0, 0))
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle([pad, pad + h * 0.03, pad + width, pad + h * 1.03],
                         radius=radius, fill=(0, 0, 0, 175))
    shadow = shadow.filter(ImageFilter.GaussianBlur(pad * 0.55))
    canvas.alpha_composite(shadow)

    mask = Image.new("L", (width, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, width - 1, h - 1],
                                           radius=radius, fill=255)
    canvas.paste(shot, (pad, pad), mask)
    return canvas, pad


def paste_card(layer, card, pad, cx, top, alpha=1.0):
    """把卡片贴到画布指定位置（cx 为卡片中心 x）。"""
    if alpha <= 0.01:
        return
    c = card if alpha >= 0.99 else card.copy()
    if alpha < 0.99:
        a = c.split()[3].point(lambda v: int(v * alpha))
        c.putalpha(a)
    layer.alpha_composite(c, (int(cx - card.width / 2), int(top - pad)))


def text_a(layer, xy, s, f, color, alpha=1.0, anchor="la"):
    if alpha <= 0.01:
        return
    ImageDraw.Draw(layer).text(xy, s, font=f, fill=rgba(color, alpha),
                               anchor=anchor)


def pill_a(layer, xy, s, size, bgc, fgc, alpha=1.0, padx=28, pady=14,
           anchor="lt", outline=None):
    if alpha <= 0.01:
        return None
    d = ImageDraw.Draw(layer)
    f = font(size, True)
    tw = d.textlength(s, font=f)
    x, y = xy
    w, h = int(tw + padx * 2), int(size + pady * 2)
    box = [x, y, x + w, y + h]
    d.rounded_rectangle(box, radius=h // 2, fill=rgba(bgc, alpha),
                        outline=rgba(outline, alpha) if outline else None,
                        width=2 if outline else 1)
    d.text((x + w / 2, y + h / 2 - size * 0.06), s, font=f,
           fill=rgba(fgc, alpha), anchor="mm")
    return box


# ------------------------------------------------------------------ 场景
def scene_hook(W, H, vertical):
    bg = bg_for((W, H))
    f1 = font(int(H * (0.115 if vertical else 0.132)))
    f2 = font(int(H * (0.115 if vertical else 0.132)))
    f3 = font(int(H * (0.030 if vertical else 0.032)))
    base_y = int(H * (0.30 if vertical else 0.31))

    def draw(t):
        layer = bg.copy()
        a1 = anim(t, 0.05, 0.55)
        text_a(layer, (W / 2, base_y - (1 - a1) * H * 0.03), "同一句话", f1,
               WHITE, a1, "mm")
        a2 = anim(t, 0.35, 0.55)
        text_a(layer, (W / 2, base_y + H * 0.155 - (1 - a2) * H * 0.03),
               "十种结果", f2, ACCENT_SOFT, a2, "mm")
        a3 = anim(t, 0.75, 0.55)
        text_a(layer, (W / 2, base_y + H * 0.275), "不是 AI 笨，是你没把话说清楚",
               f3, SUB, a3, "mm")
        return layer
    return draw


def scene_pain(W, H, vertical):
    bg = bg_for((W, H))
    margin = int(W * 0.07) if vertical else 132
    ft = font(int(H * (0.050 if vertical else 0.066)))
    fs = font(int(H * (0.024 if vertical else 0.030)))
    fb = font(int(H * (0.028 if vertical else 0.036)), True)
    bub = "帮我做个记账的东西"
    bw = int(ImageDraw.Draw(bg).textlength(bub, font=fb)) + 80
    bh = int(H * (0.062 if vertical else 0.078))
    by = int(H * (0.40 if vertical else 0.41))
    gaps = ["用在哪？", "给谁看？", "什么算做完？"]

    def draw(t):
        layer = bg.copy()
        a = anim(t, 0.05, 0.55)
        text_a(layer, (margin, int(H * (0.12 if vertical else 0.14)) - (1 - a) * 24),
               "你漏掉的，模型不会替你补", ft, WHITE, a)
        a2 = anim(t, 0.30, 0.55)
        text_a(layer, (margin, int(H * (0.12 if vertical else 0.14))
                       + int(H * (0.075 if vertical else 0.092))),
               "措辞不是难点，信息缺口才是", fs, SUB, a2)

        ab = anim(t, 0.55, 0.5)
        d = ImageDraw.Draw(layer)
        d.rounded_rectangle([margin, by + (1 - ab) * 30, margin + bw,
                             by + bh + (1 - ab) * 30], radius=int(bh * 0.28),
                            fill=rgba(ACCENT, ab))
        if ab > 0.02:
            d.text((margin + bw / 2, by + bh / 2 + (1 - ab) * 30), bub, font=fb,
                   fill=rgba(WHITE, ab), anchor="mm")

        if vertical:
            y = by + bh + int(H * 0.05)
            for i, g in enumerate(gaps):
                aa = anim(t, 1.0 + i * 0.22, 0.5)
                pill_a(layer, (margin, y + (1 - aa) * 26), g, int(H * 0.026),
                       DARK_CARD, GOLD, aa, outline=GOLD)
                y += int(H * 0.058)
            a3 = anim(t, 1.75, 0.5)
            text_a(layer, (margin, y + int(H * 0.014)),
                   "模型只能猜，猜出来自然不对味", font(int(H * 0.022)), SUB, a3)
        else:
            x = margin
            y = by + bh + int(H * 0.055)
            fg = font(int(H * 0.038), True)
            for i, g in enumerate(gaps):
                aa = anim(t, 1.0 + i * 0.20, 0.5)
                if aa > 0.02:
                    pill_a(layer, (x, y + (1 - aa) * 26), g, int(H * 0.038),
                           DARK_CARD, GOLD, aa, outline=GOLD)
                x += int(d.textlength(g, font=fg)) + 68 + 32
            a3 = anim(t, 1.7, 0.5)
            text_a(layer, (margin, y + int(H * 0.105)),
                   "模型只能猜，猜出来的东西自然不对味", fs, SUB, a3)
        return layer
    return draw


def scene_intro(W, H, vertical):
    bg = bg_for((W, H))
    margin = int(W * 0.08) if vertical else 132
    card, pad = card_layer(os.path.join(SHOTS, "welcome.png"),
                           int(W * 0.84) if vertical else int(W * 0.50))
    f1 = font(int(H * (0.075 if vertical else 0.128)))
    f2 = font(int(H * (0.030 if vertical else 0.042)))
    fb = font(int(H * (0.023 if vertical else 0.029)))
    bullets = ["全本地运行，不联网上传", "零第三方依赖，绿色版双击即用",
               "编程 / 办公 / 图像 三场景"]
    if vertical:
        card_top, bull_y0 = int(H * 0.235), int(H * 0.60)
    else:
        card_top, bull_y0 = int(H * 0.165), int(H * 0.52)

    def draw(t):
        layer = bg.copy()
        a = anim(t, 0.05, 0.6)
        if vertical:
            text_a(layer, (margin, int(H * 0.06) - (1 - a) * 26), "轻提", f1, WHITE, a)
            a2 = anim(t, 0.35, 0.55)
            text_a(layer, (margin, int(H * 0.145)), "本地提示词优化器", f2,
                   ACCENT_SOFT, a2)
        else:
            text_a(layer, (margin, int(H * 0.21) - (1 - a) * 26), "轻提", f1,
                   WHITE, a)
            a2 = anim(t, 0.35, 0.55)
            text_a(layer, (margin, int(H * 0.375)), "本地提示词优化器", f2,
                   ACCENT_SOFT, a2)

        ac = anim(t, 0.45, 0.75)
        cx = W / 2 if vertical else int(W * 0.66)
        paste_card(layer, card, pad, cx, card_top + (1 - ac) * H * 0.03, ac)

        for i, s in enumerate(bullets):
            ab = anim(t, 0.95 + i * 0.22, 0.5)
            text_a(layer, (margin + (1 - ab) * 24, bull_y0 + i * int(H * 0.058)),
                   "· " + s, fb, SUB, ab)
        return layer
    return draw


def scene_ask(W, H, vertical):
    bg = bg_for((W, H))
    margin = int(W * 0.08) if vertical else 132
    card_w = int(W * 0.84) if vertical else int(W * 0.50)
    card, pad = card_layer(os.path.join(SHOTS, "ask.png"), card_w)
    f1 = font(int(H * (0.058 if vertical else 0.064)))
    fs = font(int(H * (0.024 if vertical else 0.030)))
    if vertical:
        card_top = int(H * 0.19)
        lines = None
    else:
        card_top = int(H * 0.125)
        lines = [("★ 每题都标了推荐项", GOLD, 1.05),
                 ("「就这些，开始吧」一键跳过", ACCENT_SOFT, 1.42),
                 ("最多三轮，问完必出结果", SUB, 1.79)]

    # 鼠标点击演示：卡片内「就这些，开始吧」附近的相对位置
    click_rel = (0.231, 0.727)   # 截图里「就这些，开始吧」按钮的中心

    def draw(t):
        layer = bg.copy()
        a = anim(t, 0.05, 0.55)
        if vertical:
            text_a(layer, (margin, int(H * 0.05) - (1 - a) * 24), "它先反问你",
                   f1, WHITE, a)
            text_a(layer, (margin, int(H * 0.115)), "带选项、标推荐，懒得答也能跳过",
                   fs, SUB, anim(t, 0.3, 0.5))
        else:
            text_a(layer, (margin, int(H * 0.095) - (1 - a) * 24), "它先反问你",
                   f1, WHITE, a)
            text_a(layer, (margin, int(H * 0.175)), "带选项的问题，点一下就完事",
                   fs, SUB, anim(t, 0.3, 0.5))

        ac = anim(t, 0.40, 0.70)
        cx = W / 2 if vertical else int(W * 0.66)
        paste_card(layer, card, pad, cx, card_top + (1 - ac) * H * 0.035, ac)

        if vertical:
            y = card_top + card.height - pad + int(H * 0.02)
            for i, (s, c, st) in enumerate([("★ 每题都标了推荐项", GOLD, 1.0),
                                            ("「就这些，开始吧」一键跳过", ACCENT_SOFT, 1.35)]):
                aa = anim(t, st, 0.5)
                pill_a(layer, (margin, y + i * int(H * 0.048)), s, int(H * 0.021),
                       (28, 34, 50) if c is not GOLD else (56, 46, 20), c, aa)
        else:
            for i, (s, c, st) in enumerate(lines):
                aa = anim(t, st, 0.5)
                text_a(layer, (margin + (1 - aa) * 22, int(H * 0.30) + i * int(H * 0.082)),
                       s, font(int(H * 0.031), True), c, aa)

        # 点击演示：3.5s 后光标滑入并点一下
        cc = clamp01((t - 3.10) / 0.85)
        if cc > 0:
            left = cx - card.width / 2 + pad
            top = card_top
            iw = card.width - pad * 2
            ih = card.height - pad * 2
            tx = left + iw * click_rel[0]
            ty = top + ih * click_rel[1]
            sx, sy = left + iw * 0.92, top + ih * 1.02
            k = ease_out(cc)
            cxp = sx + (tx - sx) * k
            cyp = sy + (ty - sy) * k
            # 目标按钮高亮
            d0 = ImageDraw.Draw(layer)
            hb = [tx - iw * 0.052, ty - ih * 0.026,
                  tx + iw * 0.052, ty + ih * 0.026]
            d0.rounded_rectangle(hb, radius=int(card.height * 0.035),
                                 outline=rgba(ACCENT_SOFT, 0.9 * cc), width=3)
            ring = clamp01((t - 3.95) / 0.55)
            d = ImageDraw.Draw(layer)
            if 0 < ring < 1:
                r = int(10 + 46 * ease_out(ring))
                d.ellipse([cxp - r, cyp - r, cxp + r, cyp + r],
                          outline=rgba(ACCENT_SOFT, 1 - ring), width=4)
            if cc > 0.02:
                arrow = [(cxp, cyp), (cxp - 3, cyp + 34), (cxp + 9, cyp + 25),
                         (cxp + 17, cyp + 44), (cxp + 27, cyp + 39),
                         (cxp + 19, cyp + 21), (cxp + 33, cyp + 20)]
                d.polygon(arrow, fill=rgba(WHITE, 0.95),
                          outline=rgba((20, 20, 20), 0.9))
        return layer
    return draw


def scene_result(W, H, vertical):
    bg = bg_for((W, H))
    margin = int(W * 0.08) if vertical else 132
    card_w = int(W * 0.84) if vertical else int(W * 0.50)
    card, pad = card_layer(os.path.join(SHOTS, "result.png"), card_w)
    f1 = font(int(H * (0.058 if vertical else 0.064)))
    fs = font(int(H * (0.024 if vertical else 0.030)))
    sections = ["目标", "使用场景", "必须包含", "技术要求", "验收标准"]
    if vertical:
        card_top = int(H * 0.175)
    else:
        card_top = int(H * 0.13)

    def draw(t):
        layer = bg.copy()
        a = anim(t, 0.05, 0.55)
        if vertical:
            text_a(layer, (margin, int(H * 0.045) - (1 - a) * 24), "三十秒后",
                   f1, WHITE, a)
            text_a(layer, (margin, int(H * 0.108)), "拿到能直接用的提示词", fs,
                   ACCENT_SOFT, anim(t, 0.28, 0.5))
        else:
            text_a(layer, (margin, int(H * 0.085) - (1 - a) * 24), "三十秒后",
                   f1, WHITE, a)
            text_a(layer, (margin, int(H * 0.175)), "拿到能直接用的提示词", fs,
                   ACCENT_SOFT, anim(t, 0.28, 0.5))

        ac = anim(t, 0.38, 0.70)
        cx = W / 2 if vertical else int(W * 0.66)
        paste_card(layer, card, pad, cx, card_top + (1 - ac) * H * 0.035, ac)

        d = ImageDraw.Draw(layer)
        f = font(int(H * (0.019 if vertical else 0.030)), True)
        if vertical:
            x, y = margin, card_top + card.height - pad + int(H * 0.028)
            for i, s in enumerate(sections):
                aa = anim(t, 0.9 + i * 0.16, 0.45)
                if aa <= 0.02:
                    continue
                w = int(d.textlength(s, font=f)) + 44
                if x + w > W - margin:
                    x, y = margin, y + int(H * 0.042)
                pop = 1 + 0.10 * (1 - aa)
                h = int(H * 0.036 * pop)
                d.rounded_rectangle([x, y - (h - int(H * 0.036)) / 2, x + w,
                                     y + h - (h - int(H * 0.036)) / 2],
                                    radius=11, fill=rgba(DARK_CARD, aa),
                                    outline=rgba(ACCENT, aa), width=2)
                d.text((x + w / 2, y + int(H * 0.018)), s, font=f,
                       fill=rgba(ACCENT_SOFT, aa), anchor="mm")
                x += w + 12
        else:
            y = int(H * 0.28)
            for i, s in enumerate(sections):
                aa = anim(t, 0.85 + i * 0.15, 0.45)
                if aa <= 0.02:
                    continue
                w = int(d.textlength(s, font=f)) + 80
                off = (1 - aa) * 30
                d.rounded_rectangle([margin - off, y, margin + w - off,
                                     y + int(H * 0.070)], radius=13,
                                    fill=rgba(DARK_CARD, aa),
                                    outline=rgba(ACCENT, aa), width=2)
                d.text((margin + w / 2 - off, y + int(H * 0.035)), s, font=f,
                       fill=rgba(ACCENT_SOFT, aa), anchor="mm")
                y += int(H * 0.090)
        return layer
    return draw


def scene_modes(W, H, vertical):
    bg = bg_for((W, H))
    margin = int(W * 0.08) if vertical else 132
    card_w = int(W * 0.84) if vertical else int(W * 0.52)
    card, pad = card_layer(os.path.join(SHOTS, "editor.png"), card_w)
    f1 = font(int(H * (0.050 if vertical else 0.062)))
    fs = font(int(H * (0.022 if vertical else 0.029)))
    items = [("编程", "任务 / 系统 / 迭代"),
             ("办公", "周报 · 方案 · 邮件"),
             ("图像", "文生图 / 图生图")]
    if vertical:
        card_top = int(H * 0.50)
    else:
        card_top = int(H * 0.19)

    def draw(t):
        layer = bg.copy()
        a = anim(t, 0.05, 0.55)
        text_a(layer, (margin, int(H * (0.055 if vertical else 0.085)) - (1 - a) * 24),
               "三个场景，十三套模板", f1, WHITE, a)
        text_a(layer, (margin, int(H * (0.112 if vertical else 0.172))),
               "模板就是 Markdown，改完保存即生效", fs, SUB, anim(t, 0.28, 0.5))

        d = ImageDraw.Draw(layer)
        if vertical:
            y = int(H * 0.165)
            for i, (name, desc) in enumerate(items):
                aa = anim(t, 0.55 + i * 0.18, 0.5)
                off = (1 - aa) * 60
                box = [margin - off, y, W - margin - off, y + int(H * 0.082)]
                d.rounded_rectangle(box, radius=16, fill=rgba(DARK_CARD, aa))
                d.text((margin + 34 - off, y + int(H * 0.041)), name,
                       font=font(int(H * 0.029), True), fill=rgba(WHITE, aa), anchor="lm")
                d.text((margin + 34 + int(W * 0.17) - off, y + int(H * 0.041)),
                       desc, font=font(int(H * 0.020)), fill=rgba(SUB, aa), anchor="lm")
                y += int(H * 0.095)
        else:
            y = int(H * 0.28)
            for i, (name, desc) in enumerate(items):
                aa = anim(t, 0.55 + i * 0.18, 0.5)
                off = (1 - aa) * 70
                box = [margin - off, y, int(W * 0.40) - off, y + int(H * 0.130)]
                d.rounded_rectangle(box, radius=16, fill=rgba(DARK_CARD, aa))
                d.rectangle([margin - off, y + 26, margin + 6 - off,
                             y + int(H * 0.130) - 26], fill=rgba(ACCENT, aa))
                d.text((margin + 42 - off, y + int(H * 0.040)), name,
                       font=font(int(H * 0.040), True), fill=rgba(WHITE, aa))
                d.text((margin + 42 - off, y + int(H * 0.090)), desc,
                       font=font(int(H * 0.024)), fill=rgba(SUB, aa))
                y += int(H * 0.160)

        ac = anim(t, 0.75, 0.75)
        cx = W / 2 if vertical else int(W * 0.68)
        paste_card(layer, card, pad, cx, card_top + (1 - ac) * H * 0.04, ac)
        return layer
    return draw


def scene_outro(W, H, vertical):
    bg = bg_for((W, H))
    f1 = font(int(H * (0.112 if vertical else 0.140)))
    f2 = font(int(H * (0.044 if vertical else 0.049)))
    f3 = font(int(H * (0.024 if vertical else 0.029)))
    base = int(H * (0.30 if vertical else 0.27))

    def draw(t):
        layer = bg.copy()
        # 轻微呼吸光晕，避免静止
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        r = int(W * (0.34 + 0.02 * math.sin(t * 1.4)))
        gd.ellipse([W / 2 - r, H * 0.36 - r * 0.6, W / 2 + r, H * 0.36 + r * 0.6],
                   fill=(47, 111, 237, 26))
        glow = glow.filter(ImageFilter.GaussianBlur(int(W * 0.09)))
        layer.alpha_composite(glow)

        a = clamp01(t / 0.6)
        s = 0.92 + 0.08 * ease_out_back(a)
        f = font(int(H * (0.112 if vertical else 0.140) * s))
        text_a(layer, (W / 2, base), "轻提", f, WHITE, a, "mm")
        a2 = anim(t, 0.35, 0.55)
        text_a(layer, (W / 2, base + H * 0.105), "让 AI 听懂你的大白话", f2,
               ACCENT_SOFT, a2, "mm")
        for i, line in enumerate(["全本地运行 · 密钥 DPAPI 加密",
                                  "MIT 开源 · 绿色版免安装"]):
            a3 = anim(t, 0.9 + i * 0.25, 0.5)
            text_a(layer, (W / 2, H * (0.56 if vertical else 0.55) + i * H * 0.055),
                   line, f3, SUB, a3, "mm")
        return layer
    return draw


def scene_notice(W, H, vertical):
    bg = bg_for((W, H))
    margin = int(W * 0.10) if vertical else int(W * 0.17)
    f_tag = font(int(H * (0.019 if vertical else 0.024)), True)
    f_body = font(int(H * (0.026 if vertical else 0.033)))
    # 按可用宽度自动缩字，保证最长那句不贴边
    probe = ImageDraw.Draw(bg)
    maxw = W - margin * 2
    body_size = int(H * (0.026 if vertical else 0.033))
    while body_size > 14 and max(probe.textlength(x, font=font(body_size))
                                 for x in NOTICE_LINES) > maxw:
        body_size -= 2
    f_body = font(body_size)
    lh = int(body_size * (1.9 if vertical else 1.85))
    block_h = lh * len(NOTICE_LINES)
    top = int(H * (0.34 if vertical else 0.33))

    def draw(t):
        layer = bg.copy()
        d = ImageDraw.Draw(layer)

        a0 = anim(t, 0.05, 0.45)
        tag = "AI 生成声明"
        tw = d.textlength(tag, font=f_tag)
        tw_box = tw + int(H * 0.05)
        th_box = int(H * (0.038 if vertical else 0.046))
        cx = W / 2
        y0 = top - int(H * (0.10 if vertical else 0.13))
        d.rounded_rectangle([cx - tw_box / 2, y0 - th_box / 2,
                             cx + tw_box / 2, y0 + th_box / 2],
                            radius=th_box // 2, outline=rgba(GOLD, a0), width=2)
        d.text((cx, y0), tag, font=f_tag, fill=rgba(GOLD, a0), anchor="mm")

        y = top
        for i, line in enumerate(NOTICE_LINES):
            a = anim(t, 0.45 + i * 0.35, 0.5)
            if a > 0.02:
                color = WHITE
                d.text((cx, y + lh / 2 + (1 - a) * 14), line, font=f_body,
                       fill=rgba(color, a), anchor="mm")
            y += lh

        # 关键词强调：画在正文下方的细线
        a2 = anim(t, 1.6, 0.6)
        if a2 > 0.02:
            lw = int(W * 0.16 * ease_out(a2))
            yy = top + lh * len(NOTICE_LINES) + int(H * 0.03)
            d.rectangle([cx - lw / 2, yy, cx + lw / 2, yy + max(3, int(H * 0.004))],
                        fill=rgba(ACCENT, a2))
        return layer
    return draw


BUILDERS = dict(notice=scene_notice, hook=scene_hook, pain=scene_pain, intro=scene_intro,
                ask=scene_ask, result=scene_result, modes=scene_modes,
                outro=scene_outro)


# ------------------------------------------------------------------ 常驻元素
def wrap_text(draw, text, f, maxw):
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=f) <= maxw:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def draw_beats(layer, W, H, vertical, lines, durs, t_local, T, total):
    """字幕按真实配音时长切换。"""
    d = ImageDraw.Draw(layer)
    if not lines:
        bar_y = H - max(6, int(H * 0.006))
        d.rectangle([0, bar_y, W, H], fill=(255, 255, 255, 26))
        d.rectangle([0, bar_y, int(W * clamp01(T / total)), H],
                    fill=rgba(ACCENT, 0.95))
        return layer
    acc = 0.0
    idx, local = len(lines) - 1, lines and durs[-1] or 0
    for i, dur in enumerate(durs):
        if t_local < acc + dur:
            idx, local = i, t_local - acc
            break
        acc += dur

    text = lines[min(idx, len(lines) - 1)]
    a = anim(local, 0.0, 0.28)
    rise = (1 - a) * 16

    size = int(H * (0.030 if vertical else 0.036))
    f = font(size, True)
    maxw = int(W * (0.86 if vertical else 0.78))
    out = wrap_text(d, text, f, maxw)
    lh = int(size * 1.45)
    block_h = lh * len(out)

    y_center = int(H * (0.855 if vertical else 0.885))
    x_center = W / 2

    pad_x, pad_y = int(size * 1.1), int(size * 0.55)
    tw = max(d.textlength(ln, font=f) for ln in out)
    bw = tw + pad_x * 2
    bh = block_h + pad_y * 2
    d.rounded_rectangle([x_center - bw / 2, y_center - bh / 2 + rise,
                         x_center + bw / 2, y_center + bh / 2 + rise],
                        radius=int(bh * 0.22), fill=(8, 11, 18, int(210 * a)))
    d.rounded_rectangle([x_center - bw / 2 + 10, y_center - bh / 2 + rise + 14,
                         x_center - bw / 2 + 16, y_center + bh / 2 + rise - 14],
                        radius=3, fill=rgba(ACCENT, a))
    ty = y_center - block_h / 2 + rise
    for ln in out:
        d.text((x_center, ty + lh / 2), ln, font=f, fill=rgba(WHITE, a), anchor="mm")
        ty += lh

    bar_y = H - max(6, int(H * 0.006))
    d.rectangle([0, bar_y, W, H], fill=(255, 255, 255, 26))
    d.rectangle([0, bar_y, int(W * clamp01(T / total)), H], fill=rgba(ACCENT, 0.95))
    return layer


# ------------------------------------------------------------------ 配音
VOICE = "zh-CN-XiaoxiaoNeural"
VOICE_RATE = "+12%"
VOICE_PITCH = "+0Hz"
GAP = 0.12          # 句间停顿


def _hash(text):
    import hashlib
    key = "%s|%s|%s|%s" % (VOICE, VOICE_RATE, VOICE_PITCH, text)
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:16]


def tts(text):
    """edge-tts 合成一句，返回 wav 路径（带缓存）。"""
    import edge_tts

    os.makedirs(TTS, exist_ok=True)
    base = os.path.join(TTS, _hash(text))
    mp3, wav = base + ".mp3", base + ".wav"
    if not os.path.exists(wav):
        async def go():
            c = edge_tts.Communicate(text, VOICE, rate=VOICE_RATE,
                                     pitch=VOICE_PITCH)
            await c.save(mp3)
        asyncio.run(go())
        subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error",
                        "-i", mp3, "-ar", "44100", "-ac", "1", wav], check=True)
        try:
            os.remove(mp3)
        except OSError:
            pass
    return wav


def duration(path):
    out = subprocess.run([FF, "-hide_banner", "-i", path], capture_output=True,
                         text=True, errors="ignore").stderr
    for line in out.splitlines():
        if "Duration:" in line:
            hms = line.split("Duration:")[1].split(",")[0].strip()
            h, m, sec = hms.split(":")
            return int(h) * 3600 + int(m) * 60 + float(sec)
    raise RuntimeError("probe failed: " + path)


# ------------------------------------------------------------------ 背景垫乐
def make_ambient(total, path):
    """纯 Python 合成一段极简垫乐（无版权问题），垫在人声下面。"""
    import array
    import struct

    sr = 22050
    n = int(total * sr)
    buf = array.array("h", bytes(2 * n))
    pad = [(110.0, 0.30), (164.81, 0.22), (220.0, 0.16), (261.63, 0.10)]
    noise = 0.0
    seed = 12345
    for i in range(n):
        t = i / sr
        v = 0.0
        for f, amp in pad:
            lfo = 0.82 + 0.18 * math.sin(2 * math.pi * 0.07 * t + f)
            v += amp * lfo * math.sin(2 * math.pi * f * t)
        seed = (1103515245 * seed + 12345) & 0x7FFFFFFF
        noise = noise * 0.995 + ((seed / 0x7FFFFFFF) - 0.5) * 0.005
        v = v * 0.16 + noise * 0.5
        fade = min(1.0, t / 1.2, max(0.0, (total - t) / 1.5))
        buf[i] = int(max(-1.0, min(1.0, v * fade)) * 9000)
    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + 2 * n))
        f.write(b"WAVEfmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", 2 * n))
        buf.tofile(f)
    return path


# ------------------------------------------------------------------ 合成
def make(orientation):
    vertical = orientation == "v"
    W, H = (1080, 1920) if vertical else (1920, 1080)
    tag = "v" if vertical else "h"

    print("[%s] 1/5 配音（%s %s）…" % (tag, VOICE, VOICE_RATE))
    beat_wavs, beat_durs = [], []
    for sc in SCENES:
        if sc.get("fixed"):
            beat_wavs.append([])
            beat_durs.append([sc["fixed"]])
            print("    %-6s 固定 %.1fs" % (sc["key"], sc["fixed"]))
            continue
        ws, ds = [], []
        for line in sc["lines"]:
            w = tts(line)
            ws.append(w)
            ds.append(duration(w) + GAP)
        beat_wavs.append(ws)
        beat_durs.append(ds)
        print("    %-6s %s" % (sc["key"], " / ".join("%.1f" % d for d in ds)))

    scene_len = [ds[0] if SCENES[i].get("fixed") else LEAD + sum(ds) + TAIL
                 for i, ds in enumerate(beat_durs)]
    starts, t = [], 0.0
    for i in range(len(SCENES)):
        if i:
            t += scene_len[i - 1] - XF
        starts.append(t)
    total = starts[-1] + scene_len[-1]
    print("    总长 %.1fs" % total)

    print("[%s] 2/5 逐帧渲染 %d 帧…" % (tag, int(total * FPS)))
    draws = [BUILDERS[s["key"]](W, H, vertical) for s in SCENES]
    frames = int(total * FPS)
    os.makedirs(OUT, exist_ok=True)
    video = os.path.join(OUT, "_%s_silent.mp4" % tag)
    proc = subprocess.Popen(
        [FF, "-y", "-hide_banner", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H),
         "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "medium", "-crf", "19",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", video],
        stdin=subprocess.PIPE)

    for fi in range(frames):
        T = fi / FPS
        idx = max(0, min(len(SCENES) - 1,
                         max(i for i, st in enumerate(starts) if st <= T + 1e-6)))
        img = draws[idx](T - starts[idx])
        nxt = idx + 1
        if nxt < len(SCENES) and T > starts[nxt] - XF:
            w = clamp01((T - (starts[nxt] - XF)) / XF)
            img = Image.blend(img, draws[nxt](T - starts[nxt]), w)
        sc = SCENES[idx]
        draw_beats(img, W, H, vertical, sc["lines"], beat_durs[idx],
                   T - starts[idx], T, total)
        proc.stdin.write(img.convert("RGB").tobytes())
        if fi % 300 == 0:
            print("    %d/%d" % (fi, frames), flush=True)
    proc.stdin.close()
    proc.wait()
    if proc.returncode:
        raise SystemExit("ffmpeg encode failed")

    print("[%s] 3/5 铺人声…" % tag)
    inputs, filters, mix_labels = [], [], []
    k = 0
    for i, ws in enumerate(beat_wavs):
        if not ws:
            continue
        pos = starts[i] + LEAD
        for w, dur in zip(ws, beat_durs[i]):
            inputs += ["-i", w]
            ms = int(pos * 1000)
            filters.append("[%d:a]aresample=44100,adelay=%d|%d,apad=whole_dur=%.2f[v%d]"
                           % (k, ms, ms, total, k))
            mix_labels.append("[v%d]" % k)
            pos += dur
            k += 1
    filters.append("%samix=inputs=%d:normalize=0:duration=longest,"
                   "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=44100[voice]"
                   % ("".join(mix_labels), k))

    print("[%s] 4/5 垫乐 + 混音…" % tag)
    pad = os.path.join(OUT, "_%s_pad.wav" % tag)
    make_ambient(total, pad)
    inputs += ["-i", pad]
    filters.append("[%d:a]aresample=44100,volume=0.16[pad]" % k)
    filters.append("[voice][pad]amix=inputs=2:normalize=0:duration=first,"
                   "alimiter=limit=0.97[aout]" % ())
    m4a = os.path.join(OUT, "_%s_audio.m4a" % tag)
    subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error", *inputs,
                    "-filter_complex", ";".join(filters), "-map", "[aout]",
                    "-c:a", "aac", "-b:a", "192k", "-t", "%.2f" % total,
                    m4a], check=True)

    print("[%s] 5/5 合成…" % tag)
    name = ("轻提-宣传片-竖版1080x1920.mp4" if vertical
            else "轻提-宣传片-横版1920x1080.mp4")
    final = os.path.join(OUT, name)
    subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error",
                    "-i", video, "-i", m4a, "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-c:a", "copy", "-shortest",
                    "-movflags", "+faststart", final], check=True)
    os.remove(video)
    os.remove(m4a)
    os.remove(pad)
    print("    成片：%s  %.1fs" % (final, total))
    return final, total


def cover():
    os.makedirs(OUT, exist_ok=True)
    made = []
    for (W, H), name in [((1920, 1080), "封面-横版1920x1080.png"),
                         ((1080, 1440), "封面-竖版1080x1440.png")]:
        c = bg_for((W, H)).convert("RGB")
        d = ImageDraw.Draw(c)
        tag = "开源 · MIT 协议 · 绿色版免安装"
        ft = font(int(H * 0.026))
        tw = d.textlength(tag, font=ft)
        d.rounded_rectangle([W / 2 - tw / 2 - 30, int(H * 0.075),
                             W / 2 + tw / 2 + 30, int(H * 0.075) + int(H * 0.055)],
                            radius=int(H * 0.0275), fill=DARK_CARD)
        d.text((W / 2, int(H * 0.075) + int(H * 0.0275)), tag, font=ft,
               fill=ACCENT_SOFT, anchor="mm")
        d.text((W / 2, int(H * 0.27)), "轻提", font=font(int(H * 0.13)), fill=WHITE,
               anchor="mm")
        d.text((W / 2, int(H * 0.375)), "让 AI 听懂你的大白话",
               font=font(int(H * 0.052)), fill=ACCENT_SOFT, anchor="mm")
        d.text((W / 2, int(H * 0.455)), "本地提示词优化器 · 先反问再动笔",
               font=font(int(H * 0.032)), fill=SUB, anchor="mm")

        top = int(H * 0.545)
        avail_h = H - top - int(H * 0.06)
        cw = min(int(avail_h * AR), int(W * 0.80))
        card, pad = card_layer(os.path.join(SHOTS, "ask.png"), cw)
        c.paste(card, (int(W / 2 - card.width / 2), top - pad), card)
        p2 = os.path.join(OUT, name)
        c.save(p2, optimize=True)
        made.append(p2)
    return made


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    done = []
    if which == "cover":
        done = [(p, 0) for p in cover()]
    else:
        if which in ("h", "both"):
            done.append(make("h"))
        if which in ("v", "both"):
            done.append(make("v"))
    for p, t in done:
        print("OK", p, "%.1fs" % t)


if __name__ == "__main__":
    main()
