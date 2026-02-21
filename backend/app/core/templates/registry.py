import json
import re
from pathlib import Path


BUILTIN_DIR = Path(__file__).parent / "builtin"
CUSTOM_DIR = Path(__file__).parent / "custom"

# Only allow safe characters in template IDs
_SAFE_TEMPLATE_ID = re.compile(r'^[a-zA-Z0-9_-]+$')


def _scan_dir(base_dir: Path, is_builtin: bool = False) -> list[dict]:
    """Scan a directory for templates with meta.json files."""
    templates = []
    if not base_dir.exists():
        return templates

    for template_dir in sorted(base_dir.iterdir()):
        if not template_dir.is_dir():
            continue
        meta_path = template_dir / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["_dir"] = str(template_dir)
            meta["is_builtin"] = is_builtin
            templates.append(meta)

    return templates


def discover_templates() -> list[dict]:
    """Discover all templates (builtin + custom) by reading their meta.json files."""
    return _scan_dir(BUILTIN_DIR, is_builtin=True) + _scan_dir(CUSTOM_DIR, is_builtin=False)


def get_template(template_id: str) -> dict | None:
    """Get a specific template by its id."""
    for tmpl in discover_templates():
        if tmpl["id"] == template_id:
            return tmpl
    return None


def get_template_content(template_id: str) -> str | None:
    """Read the .tex.j2 template file content."""
    tmpl = get_template(template_id)
    if not tmpl:
        return None
    template_dir = Path(tmpl["_dir"])
    tex_path = template_dir / "template.tex.j2"
    if tex_path.exists():
        return tex_path.read_text(encoding="utf-8")
    return None


def get_template_dir(template_id: str) -> Path | None:
    """Return the absolute path to a template's directory."""
    tmpl = get_template(template_id)
    if not tmpl:
        return None
    return Path(tmpl["_dir"])


def get_template_support_dirs(template_id: str) -> list[Path]:
    """Return absolute paths for support_dirs listed in meta.json.

    These are static directories (e.g. Style/, Biblio/, Img/) that must be
    copied into the compilation working directory. Returns an empty list if
    the template has no support_dirs.
    """
    tmpl = get_template(template_id)
    if not tmpl:
        return []
    template_dir = Path(tmpl["_dir"])
    support_dir_names = tmpl.get("support_dirs", [])
    result = []
    for name in support_dir_names:
        d = template_dir / name
        if d.is_dir():
            result.append(d)
    return result


def delete_custom_template(template_id: str) -> bool:
    """Delete a custom template. Returns True if deleted, False if not found."""
    if not _SAFE_TEMPLATE_ID.match(template_id):
        raise ValueError(f"Invalid template_id: {template_id}")
    template_dir = CUSTOM_DIR / template_id
    if not template_dir.exists():
        return False
    import shutil
    shutil.rmtree(template_dir)
    return True


def save_custom_template(template_id: str, meta: dict, template_content: str) -> Path:
    """Save a custom template (meta.json + template.tex.j2)."""
    if not _SAFE_TEMPLATE_ID.match(template_id):
        raise ValueError(f"Invalid template_id: {template_id}")
    template_dir = CUSTOM_DIR / template_id
    template_dir.mkdir(parents=True, exist_ok=True)

    meta_path = template_dir / "meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    tex_path = template_dir / "template.tex.j2"
    tex_path.write_text(template_content, encoding="utf-8")

    return template_dir
