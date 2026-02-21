from pathlib import Path

from jinja2 import Environment, FileSystemLoader, BaseLoader


def create_jinja_env(template_dir: str | Path | None = None) -> Environment:
    """Create Jinja2 environment with custom delimiters to avoid LaTeX conflicts."""
    loader: BaseLoader | None = None
    if template_dir:
        loader = FileSystemLoader(str(template_dir))

    env = Environment(
        loader=loader,
        variable_start_string="<<",
        variable_end_string=">>",
        block_start_string="<%",
        block_end_string="%>",
        comment_start_string="<#",
        comment_end_string="#>",
        autoescape=False,
    )
    return env


def render_template(template_name: str, variables: dict, template_dir: str | Path) -> str:
    """Render a template file with the given variables."""
    env = create_jinja_env(template_dir)
    template = env.get_template(template_name)
    return template.render(**variables)


def render_string(template_string: str, variables: dict) -> str:
    """Render a template string with the given variables."""
    env = create_jinja_env()
    template = env.from_string(template_string)
    return template.render(**variables)
