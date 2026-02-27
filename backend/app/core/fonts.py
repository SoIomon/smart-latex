"""CJK font mapping — cross-platform font name resolution.

Provides platform-aware CJK font names based on the ``CJK_FONTSET``
configuration value (``mac`` / ``windows`` / ``linux``).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


# ---------------------------------------------------------------------------
# Font map: fontset → semantic role → actual font name
# ---------------------------------------------------------------------------

_FONT_MAPS: dict[str, dict[str, str]] = {
    "mac": {
        "songti": "STSong",
        "heiti": "Heiti SC",
        "kaiti": "Kaiti SC",
        "fangsong": "STFangsong",
    },
    "windows": {
        "songti": "SimSun",
        "heiti": "SimHei",
        "kaiti": "KaiTi",
        "fangsong": "FangSong",
    },
    "linux": {
        "songti": "FandolSong",
        "heiti": "FandolHei",
        "kaiti": "FandolKai",
        "fangsong": "FandolFang",
    },
}

# Reverse lookup: concrete font name → semantic role
_REVERSE_MAP: dict[str, str] = {}
for _fonts in _FONT_MAPS.values():
    for _role, _name in _fonts.items():
        _REVERSE_MAP[_name] = _role


@dataclass
class CJKFonts:
    """Resolved CJK font names for the current platform."""
    songti: str
    heiti: str
    kaiti: str
    fangsong: str


@lru_cache(maxsize=1)
def get_cjk_fonts() -> CJKFonts:
    """Return CJK font names for the configured ``CJK_FONTSET``.

    Result is cached — ``CJK_FONTSET`` is fixed at startup.
    """
    from app.config import settings

    fontset = getattr(settings, "CJK_FONTSET", "mac").lower()
    fonts = _FONT_MAPS.get(fontset, _FONT_MAPS["mac"])
    return CJKFonts(
        songti=fonts["songti"],
        heiti=fonts["heiti"],
        kaiti=fonts["kaiti"],
        fangsong=fonts["fangsong"],
    )


def resolve_cjk_font_name(name: str) -> str:
    """Translate a concrete CJK font name to the current platform's equivalent.

    For example, if ``CJK_FONTSET=windows`` and *name* is ``"STSong"``,
    returns ``"SimSun"``.  If *name* is not a known CJK font, returns it
    unchanged.
    """
    role = _REVERSE_MAP.get(name)
    if role is None:
        return name
    fonts = get_cjk_fonts()
    return getattr(fonts, role, name)
