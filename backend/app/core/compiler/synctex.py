"""SyncTeX CLI wrapper for source↔PDF bidirectional synchronization."""

import asyncio
import logging
import os
import platform
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_SYNCTEX_CMD = "synctex"


def _build_env() -> dict[str, str]:
    """Build environment with TeX binaries in PATH."""
    env = {**os.environ}
    tex_bin = "/Library/TeX/texbin"
    if platform.system() != "Windows" and Path(tex_bin).is_dir():
        env["PATH"] = f"{tex_bin}{os.pathsep}{env.get('PATH', '')}"
    return env


@dataclass
class ForwardSyncResult:
    page: int
    x: float
    y: float
    width: float
    height: float


@dataclass
class InverseSyncResult:
    filename: str
    line: int
    column: int


def _parse_forward_output(output: str) -> ForwardSyncResult | None:
    """Parse synctex view output into structured result."""
    page = x = y = w = h = None
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Page:"):
            page = int(line.split(":", 1)[1].strip())
        elif line.startswith("x:"):
            x = float(line.split(":", 1)[1].strip())
        elif line.startswith("y:"):
            y = float(line.split(":", 1)[1].strip())
        elif line.startswith("W:"):
            w = float(line.split(":", 1)[1].strip())
        elif line.startswith("H:"):
            h = float(line.split(":", 1)[1].strip())
    if page is not None and x is not None and y is not None:
        return ForwardSyncResult(
            page=page,
            x=x,
            y=y,
            width=w or 0.0,
            height=h or 0.0,
        )
    return None


def _parse_inverse_output(output: str) -> InverseSyncResult | None:
    """Parse synctex edit output into structured result."""
    filename = None
    line_num = column = None
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Input:"):
            filename = line.split(":", 1)[1].strip()
        elif line.startswith("Line:"):
            line_num = int(line.split(":", 1)[1].strip())
        elif line.startswith("Column:"):
            column = int(line.split(":", 1)[1].strip())
    if line_num is not None:
        return InverseSyncResult(
            filename=filename or "document.tex",
            line=line_num,
            column=column or 0,
        )
    return None


async def _run_synctex(args: list[str], cwd: str) -> str | None:
    """Run synctex CLI and return stdout, or None on failure."""
    env = _build_env()
    try:
        process = await asyncio.create_subprocess_exec(
            _SYNCTEX_CMD, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
        if process.returncode != 0:
            logger.warning("synctex %s failed: %s", args[0], stderr.decode(errors="replace"))
            return None
        return stdout.decode("utf-8", errors="replace")
    except FileNotFoundError:
        logger.warning("synctex command not found in PATH")
        return None
    except asyncio.TimeoutError:
        logger.warning("synctex %s timed out", args[0])
        return None
    except NotImplementedError:
        # Windows fallback
        import subprocess
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [_SYNCTEX_CMD, *args],
                capture_output=True, cwd=cwd, env=env, timeout=10,
            )
            if result.returncode != 0:
                return None
            return result.stdout.decode("utf-8", errors="replace")
        except Exception:
            return None


async def forward_sync(
    line: int, column: int, tex_file: str, pdf_path: str, cwd: str
) -> ForwardSyncResult | None:
    """Forward sync: source line → PDF position.

    Args:
        line: 1-based line number in the tex file
        column: 0-based column number
        tex_file: tex filename relative to cwd (e.g. "document.tex")
        pdf_path: PDF filename relative to cwd (e.g. "document.pdf")
        cwd: working directory containing both files
    """
    args = ["view", "-i", f"{line}:{column}:{tex_file}", "-o", pdf_path]
    output = await _run_synctex(args, cwd)
    if output is None:
        return None
    return _parse_forward_output(output)


async def inverse_sync(
    page: int, x: float, y: float, pdf_path: str, cwd: str
) -> InverseSyncResult | None:
    """Inverse sync: PDF position → source line.

    Args:
        page: 1-based page number
        x: x coordinate in PDF points (72dpi, origin top-left)
        y: y coordinate in PDF points
        pdf_path: PDF filename relative to cwd
        cwd: working directory
    """
    args = ["edit", "-o", f"{page}:{x}:{y}:{pdf_path}"]
    output = await _run_synctex(args, cwd)
    if output is None:
        return None
    return _parse_inverse_output(output)


async def build_line_map(
    tex_file: str, pdf_path: str, cwd: str, total_lines: int, step: int = 5,
) -> dict[int, dict]:
    """Build a mapping from source line numbers to PDF positions.

    Returns dict: {line_number: {page, y}} for lines that have a valid mapping.
    Uses concurrent queries with a semaphore to limit parallelism.
    """
    if total_lines > 5000:
        step = max(step, 10)

    semaphore = asyncio.Semaphore(20)

    async def query_line(line_num: int) -> tuple[int, ForwardSyncResult | None]:
        async with semaphore:
            result = await forward_sync(line_num, 0, tex_file, pdf_path, cwd)
            return line_num, result

    tasks = [query_line(ln) for ln in range(1, total_lines + 1, step)]
    results = await asyncio.gather(*tasks)

    line_map: dict[int, dict] = {}
    for line_num, result in results:
        if result is not None:
            line_map[line_num] = {"page": result.page, "y": result.y}
    return line_map
