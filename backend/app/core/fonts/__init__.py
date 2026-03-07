"""CJK font mapping — cross-platform font name resolution with bundled fallback.

Provides platform-aware CJK font names based on the ``CJK_FONTSET``
configuration value (``auto`` / ``mac`` / ``windows`` / ``linux`` / ``fandol``).

When system fonts are unavailable, automatically falls back to bundled
FandolFonts (open-source CJK fonts shipped with TeX Live).
"""

from __future__ import annotations

import json
import logging
import platform
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bundled fonts directory & version
# ---------------------------------------------------------------------------

BUNDLED_FONTS_DIR = Path(__file__).parent / "bundled"
BUNDLED_FONTS_VERSION_FILE = BUNDLED_FONTS_DIR / "VERSION.json"

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
    "fandol": {
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
    is_fallback: bool = False  # True when using bundled FandolFonts as fallback


def _detect_platform_fontset() -> str:
    """Detect the appropriate fontset based on the current OS."""
    if sys.platform == "darwin":
        return "mac"
    elif sys.platform == "win32":
        return "windows"
    else:
        return "linux"


_WINDOWS_FONT_FILES: dict[str, list[str]] = {
    "SimSun": ["simsun.ttc", "simsun.ttf"],
    "SimHei": ["simhei.ttf"],
    "KaiTi": ["simkai.ttf", "kaiti.ttf"],
    "FangSong": ["simfang.ttf", "fangsong.ttf"],
    "FandolSong": ["FandolSong-Regular.otf"],
    "FandolHei": ["FandolHei-Regular.otf"],
    "FandolKai": ["FandolKai-Regular.otf"],
    "FandolFang": ["FandolFang-Regular.otf"],
}


def _check_font_available_fclist(font_name: str) -> bool:
    """Check font availability using fc-list (works on all platforms with fontconfig)."""
    try:
        result = subprocess.run(
            ["fc-list", f":family={font_name}", "family"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _check_font_available(font_name: str) -> bool:
    """Check if a font is available on the system (synchronous).

    On Windows: tries fc-list first (available with MiKTeX/TeX Live),
    falls back to checking known font file paths.
    On Unix: uses fc-list.
    """
    if platform.system() == "Windows":
        # Try fc-list first (MiKTeX and TeX Live ship fontconfig)
        if _check_font_available_fclist(font_name):
            return True
        # Fallback: check known font file paths
        candidates = _WINDOWS_FONT_FILES.get(font_name)
        if candidates is None:
            return True  # Unknown font, assume available
        win_fonts = Path("C:/Windows/Fonts")
        user_fonts = Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts"
        for fname in candidates:
            if (win_fonts / fname).exists() or (user_fonts / fname).exists():
                return True
        return False
    return _check_font_available_fclist(font_name)


# ---------------------------------------------------------------------------
# TTL-based cache for get_cjk_fonts()
# ---------------------------------------------------------------------------

_cjk_fonts_cache: CJKFonts | None = None
_cjk_fonts_cache_time: float = 0.0
_cjk_fonts_cache_lock = threading.Lock()
_CJK_FONTS_CACHE_TTL = 300.0  # 5 minutes


def refresh_cjk_fonts() -> None:
    """Clear the CJK fonts cache so the next call re-detects fonts."""
    global _cjk_fonts_cache, _cjk_fonts_cache_time
    with _cjk_fonts_cache_lock:
        _cjk_fonts_cache = None
        _cjk_fonts_cache_time = 0.0


def get_cjk_fonts() -> CJKFonts:
    """Return CJK font names for the configured ``CJK_FONTSET``.

    When ``CJK_FONTSET`` is ``"auto"`` (the default), the platform is
    detected automatically. For each missing system font, the corresponding
    FandolFont is used as fallback.

    Result is cached with a 5-minute TTL. Call ``refresh_cjk_fonts()``
    to force re-detection (e.g. after installing fonts).
    """
    global _cjk_fonts_cache, _cjk_fonts_cache_time

    now = time.monotonic()
    with _cjk_fonts_cache_lock:
        if _cjk_fonts_cache is not None and (now - _cjk_fonts_cache_time) < _CJK_FONTS_CACHE_TTL:
            return _cjk_fonts_cache

    # Detect fonts outside the lock (may take a few seconds for fc-list)
    from app.config import settings

    fontset = getattr(settings, "CJK_FONTSET", "auto").lower()
    if fontset == "auto":
        fontset = _detect_platform_fontset()

    platform_fonts = _FONT_MAPS.get(fontset, _FONT_MAPS["fandol"])
    fandol_fonts = _FONT_MAPS["fandol"]
    is_fallback = fontset == "fandol"

    resolved: dict[str, str] = {}
    if fontset != "fandol":
        for role, font_name in platform_fonts.items():
            if _check_font_available(font_name):
                resolved[role] = font_name
            else:
                resolved[role] = fandol_fonts[role]
                is_fallback = True
                logger.info(
                    "Font '%s' (%s) not found, using fallback '%s'",
                    font_name, role, fandol_fonts[role],
                )
    else:
        resolved = dict(fandol_fonts)

    result = CJKFonts(
        songti=resolved["songti"],
        heiti=resolved["heiti"],
        kaiti=resolved["kaiti"],
        fangsong=resolved["fangsong"],
        is_fallback=is_fallback,
    )

    with _cjk_fonts_cache_lock:
        _cjk_fonts_cache = result
        _cjk_fonts_cache_time = time.monotonic()

    return result


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


def remap_cjk_fonts(content: str) -> str:
    """Replace hardcoded CJK font names in LaTeX source with the current platform's fonts.

    Scans ``\\setCJKmainfont``, ``\\setCJKsansfont``, ``\\newCJKfontfamily`` etc.
    and remaps any known cross-platform CJK font name to the value returned by
    ``get_cjk_fonts()`` for the current environment.  Idempotent — safe to call
    multiple times.
    """
    import re

    cjk = get_cjk_fonts()
    current = {
        "songti": cjk.songti,
        "heiti": cjk.heiti,
        "kaiti": cjk.kaiti,
        "fangsong": cjk.fangsong,
    }

    # Collect all concrete font names from every platform → role mapping
    name_to_role: dict[str, str] = {}
    for fonts in _FONT_MAPS.values():
        for role, name in fonts.items():
            name_to_role[name] = role

    # Build old→new replacement pairs (skip no-ops)
    replacements: dict[str, str] = {}
    for name, role in name_to_role.items():
        target = current[role]
        if name != target:
            replacements[name] = target

    if not replacements:
        return content

    # Only replace font names inside CJK font commands to avoid false positives.
    cjk_cmd_pattern = re.compile(
        r'(\\(?:setCJK(?:main|sans|mono)font|newCJKfontfamily\s*\\[a-zA-Z]+|setCJKfamilyfont\s*\{[^}]*\})'
        r'(?:\s*\[[^\]]*\])?\s*\{)([^}]+)(\})'
    )

    def replace_in_cmd(m: re.Match) -> str:
        prefix, font_name, suffix = m.group(1), m.group(2), m.group(3)
        new_name = replacements.get(font_name.strip(), font_name)
        return f"{prefix}{new_name}{suffix}"

    content = cjk_cmd_pattern.sub(replace_in_cmd, content)

    # Also replace font names inside [...] options (e.g. BoldFont=Heiti SC)
    for old_name, new_name in replacements.items():
        content = re.sub(
            r'(BoldFont\s*=\s*)' + re.escape(old_name),
            r'\1' + new_name,
            content,
        )
        content = re.sub(
            r'(ItalicFont\s*=\s*)' + re.escape(old_name),
            r'\1' + new_name,
            content,
        )

    return content


def get_bundled_fonts_dir() -> Path:
    """Return the path to the bundled fonts directory."""
    return BUNDLED_FONTS_DIR


def get_bundled_fonts_info() -> dict[str, str | list[str]]:
    """Return version and file list for bundled fonts.

    Reads ``VERSION.json`` from the bundled fonts directory.
    """
    info: dict[str, str | list[str]] = {
        "version": "unknown",
        "source": "FandolFonts (TeX Live)",
        "files": [],
    }
    if BUNDLED_FONTS_VERSION_FILE.exists():
        try:
            data = json.loads(BUNDLED_FONTS_VERSION_FILE.read_text(encoding="utf-8"))
            info.update(data)
        except (json.JSONDecodeError, OSError):
            pass
    info["files"] = sorted(f.name for f in BUNDLED_FONTS_DIR.glob("*.otf"))
    return info


def install_bundled_fonts() -> dict[str, str]:
    """Install bundled FandolFonts to the user's system font directory.

    Returns a dict with 'status' ('ok'/'error') and 'message'.
    """
    os_name = platform.system()

    if os_name == "Darwin":
        target_dir = Path.home() / "Library" / "Fonts"
    elif os_name == "Windows":
        target_dir = Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts"
    else:
        target_dir = Path.home() / ".local" / "share" / "fonts"

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        installed = []
        for font_file in BUNDLED_FONTS_DIR.glob("*.otf"):
            dest = target_dir / font_file.name
            if not dest.exists():
                shutil.copy2(font_file, dest)
                installed.append(font_file.name)

        # Refresh fontconfig cache on Linux/macOS
        if os_name != "Windows":
            try:
                subprocess.run(
                    ["fc-cache", "-f", str(target_dir)],
                    capture_output=True, timeout=30,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

        # Clear cached result so next call picks up new fonts
        refresh_cjk_fonts()

        if os_name == "Darwin":
            logger.info(
                "Fonts installed to %s. Note: macOS fontspec uses "
                "family names from ~/Library/Fonts, not OSFONTDIR.",
                target_dir,
            )

        if installed:
            return {
                "status": "ok",
                "message": f"已安装 {len(installed)} 个字体到 {target_dir}: {', '.join(installed)}",
            }
        else:
            return {
                "status": "ok",
                "message": f"字体已存在于 {target_dir}，无需重复安装",
            }
    except Exception as e:
        logger.error("Failed to install bundled fonts: %s", e)
        return {
            "status": "error",
            "message": f"安装失败: {e}",
        }
