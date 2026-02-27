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
        logger.debug("synctex: using sync subprocess fallback (Windows)")
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [_SYNCTEX_CMD, *args],
                capture_output=True, cwd=cwd, env=env, timeout=10,
            )
            if result.returncode != 0:
                logger.warning(
                    "synctex %s failed (rc=%s): %s",
                    args[0], result.returncode,
                    result.stderr.decode(errors="replace"),
                )
                return None
            return result.stdout.decode("utf-8", errors="replace")
        except FileNotFoundError:
            logger.warning("synctex command not found in PATH (Windows fallback)")
            return None
        except Exception as exc:
            logger.warning("synctex %s error in Windows fallback: %s", args[0], exc)
            return None


_INPUT_PATH_CACHE: dict[str, str] = {}


def _discover_input_path(tex_file: str, cwd: str) -> str | None:
    """Discover the input path format stored in the synctex database.

    On Windows, synctex may store paths with "./" prefix or backslashes.
    Parse the .synctex.gz to find the actual Input: path that matches our file.
    Returns the path string to use for forward sync, or None if not found.
    """
    import gzip
    synctex_gz = Path(cwd) / (Path(tex_file).stem + ".synctex.gz")
    if not synctex_gz.exists():
        # Try pdf-based name
        synctex_gz = Path(cwd) / "document.synctex.gz"
    if not synctex_gz.exists():
        return None
    try:
        with gzip.open(synctex_gz, "rt", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("Input:"):
                    # Format: "Input:1:./document.tex" or "Input:1:document.tex"
                    parts = line.strip().split(":", 2)
                    if len(parts) >= 3:
                        stored_path = parts[2]
                        # Check if this matches our tex_file (basename comparison)
                        if Path(stored_path).name == Path(tex_file).name:
                            logger.info("synctex: discovered input path format %r for %r", stored_path, tex_file)
                            return stored_path
    except Exception as exc:
        logger.debug("synctex: failed to parse synctex.gz: %s", exc)
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
    # Use cached input path if available, otherwise try original
    cache_key = f"{cwd}:{tex_file}"
    effective_path = _INPUT_PATH_CACHE.get(cache_key, tex_file)

    args = ["view", "-i", f"{line}:{column}:{effective_path}", "-o", pdf_path]
    output = await _run_synctex(args, cwd)
    if output is not None:
        result = _parse_forward_output(output)
        if result is not None:
            return result

    # First attempt failed; discover the correct path from synctex database
    if cache_key not in _INPUT_PATH_CACHE:
        discovered = await asyncio.to_thread(_discover_input_path, tex_file, cwd)
        if discovered and discovered != effective_path:
            _INPUT_PATH_CACHE[cache_key] = discovered
            logger.info("synctex view: retrying with discovered path %r", discovered)
            args2 = ["view", "-i", f"{line}:{column}:{discovered}", "-o", pdf_path]
            output2 = await _run_synctex(args2, cwd)
            if output2 is not None:
                result2 = _parse_forward_output(output2)
                if result2 is not None:
                    return result2
        else:
            # Mark as tried so we don't re-discover every call
            _INPUT_PATH_CACHE[cache_key] = effective_path
            if output:
                logger.debug(
                    "synctex view: no parseable data, output=%r",
                    output[:500],
                )

    return None


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
