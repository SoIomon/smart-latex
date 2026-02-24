import logging
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def create_sandbox(project_output_dir: Path) -> Path:
    """Create an isolated temporary directory for compilation."""
    sandbox_dir = project_output_dir / "build"
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    return sandbox_dir


def cleanup_sandbox(sandbox_dir: Path):
    """Remove temporary build files, keeping PDF, tex, aux, and subdirectories.

    Subdirectories (e.g. ``Img/``, ``Style/``) are preserved because they
    may contain images or support files needed for Word export.
    """
    if not sandbox_dir.exists():
        return
    _KEEP_SUFFIXES = {".pdf", ".tex", ".aux"}
    for f in sandbox_dir.iterdir():
        try:
            if f.is_dir():
                continue  # keep subdirectories (images, support files)
            # .synctex.gz has double extension; Path.suffix only returns .gz
            if f.name.endswith(".synctex.gz"):
                continue
            if f.suffix not in _KEEP_SUFFIXES:
                f.unlink()
        except OSError as e:
            logger.warning(f"Failed to clean up {f}: {e}")
