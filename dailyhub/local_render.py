"""本地 Pillow 文字卡片渲染（html_render 不可用时的通用兜底）。

从 render 拆出：渲染后端是独立职责，且依赖可选的 Pillow（缺失则不可用、自动回退纯文字）。
含 CJK 字体发现（移植自旧 epic 插件）。不依赖 AstrBot。
"""

import base64
import io
import subprocess
from pathlib import Path
from typing import Optional

from .log import logger

try:
    from PIL import Image as PILImage, ImageDraw, ImageFont

    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

_CJK_FONT_KEYWORDS = [
    "noto sans cjk",
    "noto sans sc",
    "source han sans",
    "microsoft yahei",
    "msyh",
    "pingfang",
    "simhei",
    "heiti",
    "wqy",
    "wenquanyi",
    "droid sans fallback",
    "simsun",
    "songti",
]
_FONT_SCAN_DIRS = [
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    "C:/Windows/Fonts",
    "/System/Library/Fonts",
    "/Library/Fonts",
    str(Path.home() / ".local/share/fonts"),
    str(Path.home() / ".fonts"),
]


def _discover_cjk_font() -> Optional[str]:
    # 优先 fc-list（Linux/macOS）
    try:
        r = subprocess.run(
            ["fc-list", ":lang=zh", "--format=%{file}\n"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        cands = [x.strip() for x in r.stdout.splitlines() if x.strip()]
        for kw in _CJK_FONT_KEYWORDS:
            for p in cands:
                if kw in p.lower():
                    return p
        if cands:
            return cands[0]
    except Exception:  # noqa: BLE001
        pass
    # 回退：扫描常见字体目录
    files = []
    for d in _FONT_SCAN_DIRS:
        p = Path(d)
        if not p.is_dir():
            continue
        try:
            for f in p.rglob("*"):
                if f.suffix.lower() in (".ttf", ".ttc", ".otf") and f.is_file():
                    files.append(str(f))
        except (PermissionError, OSError):
            continue
    for kw in _CJK_FONT_KEYWORDS:
        for p in files:
            if kw in p.lower():
                return p
    return files[0] if files else None


class LocalCardRenderer:
    """把一段文字渲染成卡片图（JPEG base64）。字体只探测一次并缓存。"""

    def __init__(self):
        self._font_path: Optional[str] = None
        self._font_done = False

    def render(self, text: str, dark: bool) -> Optional[str]:
        """成功返回 base64；Pillow 缺失 / 无字体 / 异常返回 None。"""
        if not HAS_PILLOW:
            return None
        fp = self._find_font()
        if not fp:
            return None
        try:
            return self._to_png_b64(text, fp, dark)
        except Exception as e:  # noqa: BLE001
            logger.warning("[render] 本地渲染失败: %s", e)
            return None

    def _find_font(self) -> Optional[str]:
        if not self._font_done:
            self._font_done = True
            self._font_path = _discover_cjk_font()
            if self._font_path:
                logger.info("[render] 本地渲染字体: %s", self._font_path)
            else:
                logger.warning("[render] 未找到 CJK 字体，本地渲染不可用")
        return self._font_path

    def _to_png_b64(self, text: str, fp: str, dark: bool) -> str:
        S = 2
        pad = 24 * S
        width = 660 * S
        bg = (23, 27, 36) if dark else (238, 241, 246)
        fg = (210, 220, 230) if dark else (40, 45, 55)
        accent = (120, 180, 245) if dark else (40, 90, 180)
        f_body = ImageFont.truetype(fp, 17 * S)
        f_title = ImageFont.truetype(fp, 22 * S)
        max_w = width - pad * 2

        raw_lines = (text or "").split("\n")
        rendered: list = []  # (segment, font, color)
        for idx, ln in enumerate(raw_lines):
            font = f_title if idx == 0 else f_body
            color = accent if idx == 0 else fg
            if not ln.strip():
                rendered.append(("", f_body, fg))
                continue
            for seg in self._wrap(ln, font, max_w):
                rendered.append((seg, font, color))

        def lh(font):
            b = font.getbbox("Ag中")
            return (b[3] - b[1]) + 10 * S

        total_h = pad * 2 + sum(lh(f) for _, f, _ in rendered)
        total_h = max(total_h, 120 * S)

        img = PILImage.new("RGB", (width, total_h), bg)
        draw = ImageDraw.Draw(img)
        y = pad
        for seg, font, color in rendered:
            draw.text((pad, y), seg, fill=color, font=font)
            y += lh(font)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90, optimize=True)
        img.close()
        return base64.b64encode(buf.getvalue()).decode("ascii")

    @staticmethod
    def _wrap(text: str, font, max_w: int) -> list:
        """按像素宽度逐字符换行（适配中英文混排）。"""
        lines, cur = [], ""
        for ch in text:
            if font.getlength(cur + ch) <= max_w:
                cur += ch
            else:
                if cur:
                    lines.append(cur)
                cur = ch
        if cur:
            lines.append(cur)
        return lines or [""]
