import asyncio
import logging
import platform
import shutil
import sys

import httpx
from fastapi import APIRouter
from openai import AsyncOpenAI
from pydantic import BaseModel
from sqlalchemy import select

from app.api.schemas.schemas import LLMConfigResponse, LLMConfigUpdate
from app.config import settings
from app.core.compiler.engine import _build_tex_env, _run_subprocess
from app.core.fonts import get_cjk_fonts, _detect_platform_fontset, install_bundled_fonts
from app.core.llm.client import doubao_client, get_llm_config, refresh_llm_config
from app.models.database import async_session
from app.models.models import LLMConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


class LLMTestResponse(BaseModel):
    success: bool
    message: str


def _mask_api_key(key: str) -> str:
    """Mask API key for display, e.g. 'sk-abc...xyzw' → 'sk-****xyzw'."""
    if not key or len(key) <= 8:
        return "****"
    return key[:3] + "****" + key[-4:]


@router.get("/llm", response_model=LLMConfigResponse)
async def get_llm_settings():
    """Return current LLM configuration (API key is masked)."""
    cfg = await get_llm_config()
    return LLMConfigResponse(
        api_key_masked=_mask_api_key(cfg["api_key"]),
        base_url=cfg["base_url"],
        model=cfg["model"],
        updated_at=cfg["updated_at"],
    )


@router.put("/llm", response_model=LLMConfigResponse)
async def update_llm_settings(body: LLMConfigUpdate):
    """Update LLM configuration. Only non-null fields are updated."""
    async with async_session() as session:
        result = await session.execute(select(LLMConfig).where(LLMConfig.id == 1))
        row = result.scalar_one_or_none()
        if not row:
            row = LLMConfig(id=1)
            session.add(row)

        if body.api_key is not None:
            row.api_key = body.api_key
        if body.base_url is not None:
            row.base_url = body.base_url
        if body.model is not None:
            row.model = body.model

        await session.commit()
        await session.refresh(row)

        refresh_llm_config()
        doubao_client.reconfigure(row.api_key, row.base_url, row.model)

        return LLMConfigResponse(
            api_key_masked=_mask_api_key(row.api_key),
            base_url=row.base_url,
            model=row.model,
            updated_at=row.updated_at.isoformat() if row.updated_at else None,
        )


@router.post("/llm/test", response_model=LLMTestResponse)
async def test_llm_connection(body: LLMConfigUpdate):
    """Test connectivity with the given (or current saved) LLM configuration."""
    cfg = await get_llm_config()

    api_key = body.api_key if body.api_key is not None else cfg["api_key"]
    base_url = body.base_url if body.base_url is not None else cfg["base_url"]
    model = body.model if body.model is not None else cfg["model"]

    try:
        async with AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=httpx.Timeout(15.0, connect=5.0),
            max_retries=0,
        ) as client:
            resp = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=5,
            )
            if resp.choices:
                return LLMTestResponse(success=True, message="连接成功")
            return LLMTestResponse(success=False, message="模型返回空结果")
    except Exception as e:
        logger.warning("LLM connection test failed: %s", e)
        # Only expose the exception type, not the full message
        # (which may contain API keys or internal URLs)
        err_type = type(e).__name__
        return LLMTestResponse(success=False, message=f"连接失败 ({err_type})")


# ---------------------------------------------------------------------------
# Environment diagnostics
# ---------------------------------------------------------------------------

class DiagnosticItem(BaseModel):
    name: str
    status: str  # "ok" | "warning" | "error"
    message: str
    suggestion: str = ""


class DiagnosticsResponse(BaseModel):
    platform: str
    items: list[DiagnosticItem]


async def _check_command(cmd: str, args: list[str], env: dict) -> tuple[bool, str]:
    """Run a command and return (success, version_string)."""
    try:
        returncode, stdout, stderr = await _run_subprocess(
            [cmd] + args, cwd=".", env=env, timeout=10,
        )
        output = (stdout + stderr).strip()
        return returncode == 0, output
    except (FileNotFoundError, asyncio.TimeoutError):
        return False, ""


async def _check_font(font_name: str, env: dict) -> bool:
    """Check if a font is available via fc-list (Unix) or fontspec test compile."""
    if platform.system() == "Windows":
        # On Windows, try a minimal xelatex compile to test the font
        import tempfile
        from pathlib import Path
        work_dir = Path(tempfile.mkdtemp(prefix="font_check_"))
        try:
            tex = f"\\documentclass{{article}}\\usepackage{{fontspec}}\\setmainfont{{{font_name}}}\\begin{{document}}x\\end{{document}}"
            tex_path = work_dir / "test.tex"
            tex_path.write_text(tex, encoding="utf-8")
            returncode, _, _ = await _run_subprocess(
                ["xelatex", "-draftmode", "-interaction=nonstopmode",
                 "-halt-on-error", "test.tex"],
                cwd=str(work_dir), env=env, timeout=15,
            )
            return returncode == 0
        except (FileNotFoundError, asyncio.TimeoutError):
            return False
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
    else:
        # Unix: use fc-list
        try:
            returncode, stdout, _ = await _run_subprocess(
                ["fc-list", f":family={font_name}", "family"],
                cwd=".", env=env, timeout=5,
            )
            return returncode == 0 and bool(stdout.strip())
        except (FileNotFoundError, asyncio.TimeoutError):
            return False


@router.get("/diagnostics", response_model=DiagnosticsResponse)
async def run_diagnostics():
    """Run environment diagnostics: platform, LaTeX, fonts, etc."""
    items: list[DiagnosticItem] = []
    env = _build_tex_env()
    os_name = platform.system()
    fontset = _detect_platform_fontset()

    # 1. Platform info
    items.append(DiagnosticItem(
        name="操作系统",
        status="ok",
        message=f"{os_name} {platform.release()} ({platform.machine()})",
    ))

    # 2. Python version
    items.append(DiagnosticItem(
        name="Python",
        status="ok",
        message=f"{sys.version.split()[0]}",
    ))

    # 3. LaTeX compiler (latexmk / xelatex)
    latex_cmd = settings.LATEX_CMD
    ok, output = await _check_command(latex_cmd, ["--version"], env)
    if ok:
        version_line = output.split("\n")[0][:100]
        items.append(DiagnosticItem(
            name=f"LaTeX 编译器 ({latex_cmd})",
            status="ok",
            message=version_line,
        ))
    else:
        items.append(DiagnosticItem(
            name=f"LaTeX 编译器 ({latex_cmd})",
            status="error",
            message=f"未找到 {latex_cmd}，编译功能将不可用",
            suggestion=(
                "Windows: 安装 MiKTeX (https://miktex.org/) 或 TeX Live\n"
                "macOS: brew install --cask mactex 或 安装 BasicTeX\n"
                "Linux: sudo apt install texlive-xetex texlive-latex-extra"
            ) if os_name != "Windows" else (
                "请安装 MiKTeX (https://miktex.org/) 并确保已添加到系统 PATH"
            ),
        ))

    # 4. xelatex (used for validation)
    ok, output = await _check_command("xelatex", ["--version"], env)
    if ok:
        version_line = output.split("\n")[0][:100]
        items.append(DiagnosticItem(
            name="XeLaTeX 引擎",
            status="ok",
            message=version_line,
        ))
    else:
        items.append(DiagnosticItem(
            name="XeLaTeX 引擎",
            status="error",
            message="未找到 xelatex，章节验证和编译将失败",
            suggestion="请确保 TeX 发行版包含 XeLaTeX 引擎",
        ))

    # 5. CJK fonts
    fonts = get_cjk_fonts()
    font_roles = [
        ("宋体", fonts.songti),
        ("黑体", fonts.heiti),
        ("楷体", fonts.kaiti),
        ("仿宋", fonts.fangsong),
    ]

    # Run font checks in parallel
    font_checks = await asyncio.gather(
        *[_check_font(f[1], env) for f in font_roles]
    )

    is_fallback = fonts.is_fallback
    _fandol_names = {"FandolSong", "FandolHei", "FandolKai", "FandolFang"}
    all_fonts_ok = True
    for (role, font_name), available in zip(font_roles, font_checks):
        if available:
            suffix = "（内置 Fandol 字体）" if font_name in _fandol_names else ""
            items.append(DiagnosticItem(
                name=f"字体 · {role}",
                status="ok",
                message=f"{font_name} ✓{suffix}",
            ))
        else:
            all_fonts_ok = False
            items.append(DiagnosticItem(
                name=f"字体 · {role}",
                status="warning",
                message=f"未检测到 {font_name}",
                suggestion="点击下方「安装内置字体」可一键安装 FandolFonts 开源中文字体",
            ))

    if not all_fonts_ok:
        items.append(DiagnosticItem(
            name="字体集配置",
            status="warning",
            message=f"当前字体集: {fontset} (CJK_FONTSET={settings.CJK_FONTSET})",
            suggestion=(
                "部分字体缺失，可点击「安装内置字体」一键安装 FandolFonts，"
                "或在 .env 中设置 CJK_FONTSET=fandol/windows/mac/linux"
            ),
        ))
    elif is_fallback:
        items.append(DiagnosticItem(
            name="字体集配置",
            status="ok",
            message=f"使用内置 FandolFonts 字体（自动降级）",
            suggestion="如需更好的排版效果，可安装系统原生中文字体（如 macOS 宋体/黑体）",
        ))

    # 6. Quick compile test
    ok_xelatex = any(i.name.startswith("XeLaTeX") and i.status == "ok" for i in items)
    if ok_xelatex:
        import tempfile
        from pathlib import Path
        work_dir = Path(tempfile.mkdtemp(prefix="diag_compile_"))
        try:
            tex = "\\documentclass{article}\n\\begin{document}\nHello World\n\\end{document}\n"
            (work_dir / "test.tex").write_text(tex, encoding="utf-8")
            returncode, stdout, stderr = await _run_subprocess(
                ["xelatex", "-draftmode", "-interaction=nonstopmode",
                 "-halt-on-error", "test.tex"],
                cwd=str(work_dir), env=env, timeout=30,
            )
            if returncode == 0:
                items.append(DiagnosticItem(
                    name="编译测试",
                    status="ok",
                    message="基础 LaTeX 编译测试通过",
                ))
            else:
                err_lines = [l for l in (stdout + stderr).split("\n") if l.strip().startswith("!")]
                items.append(DiagnosticItem(
                    name="编译测试",
                    status="error",
                    message="基础编译测试失败" + (f": {err_lines[0]}" if err_lines else ""),
                    suggestion="TeX 发行版可能不完整，请检查安装或尝试更新: tlmgr update --all",
                ))
        except asyncio.TimeoutError:
            items.append(DiagnosticItem(
                name="编译测试",
                status="warning",
                message="编译测试超时 (30s)",
                suggestion="首次编译可能较慢（需要生成字体缓存），请稍后重试",
            ))
        except FileNotFoundError:
            pass
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    return DiagnosticsResponse(
        platform=f"{os_name} ({fontset})",
        items=items,
    )


# ---------------------------------------------------------------------------
# Font installation
# ---------------------------------------------------------------------------

class FontInstallResponse(BaseModel):
    status: str  # "ok" | "error"
    message: str


@router.post("/fonts/install", response_model=FontInstallResponse)
async def install_fonts():
    """Install bundled FandolFonts to the user's system font directory."""
    result = await asyncio.to_thread(install_bundled_fonts)
    return FontInstallResponse(**result)
