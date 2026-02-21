"""LaTeX text normalization utilities.

Shared between converter.py and table_builder.py to avoid circular imports.
"""

# LaTeX symbol commands → Unicode
SYMBOL_MAP = {
    "geq": "\u2265",      # ≥
    "leq": "\u2264",      # ≤
    "neq": "\u2260",      # ≠
    "approx": "\u2248",   # ≈
    "times": "\u00d7",    # ×
    "div": "\u00f7",      # ÷
    "pm": "\u00b1",       # ±
    "cdot": "\u00b7",     # ·
    "ldots": "\u2026",    # …
    "dots": "\u2026",     # …
    "rightarrow": "\u2192",  # →
    "leftarrow": "\u2190",   # ←
    "Rightarrow": "\u21d2",  # ⇒
    "Leftarrow": "\u21d0",   # ⇐
    "leftrightarrow": "\u2194",  # ↔
    "uparrow": "\u2191",     # ↑
    "downarrow": "\u2193",   # ↓
    "infty": "\u221e",    # ∞
    "partial": "\u2202",  # ∂
    "nabla": "\u2207",    # ∇
    "forall": "\u2200",   # ∀
    "exists": "\u2203",   # ∃
    "in": "\u2208",       # ∈
    "notin": "\u2209",    # ∉
    "subset": "\u2282",   # ⊂
    "supset": "\u2283",   # ⊃
    "cup": "\u222a",      # ∪
    "cap": "\u2229",      # ∩
    "alpha": "\u03b1",    # α
    "beta": "\u03b2",     # β
    "gamma": "\u03b3",    # γ
    "delta": "\u03b4",    # δ
    "lambda": "\u03bb",   # λ
    "mu": "\u03bc",       # μ
    "sigma": "\u03c3",    # σ
    "omega": "\u03c9",    # ω
    "pi": "\u03c0",       # π
    "theta": "\u03b8",    # θ
    "phi": "\u03c6",      # φ
    "sum": "\u2211",      # ∑
    "prod": "\u220f",     # ∏
    "int": "\u222b",      # ∫
    "sqrt": "\u221a",     # √
    "degree": "\u00b0",   # °
    "copyright": "\u00a9", # ©
    "registered": "\u00ae", # ®
    "trademark": "\u2122",  # ™
    "dag": "\u2020",      # †
    "ddag": "\u2021",     # ‡
    "S": "\u00a7",        # §
    "pounds": "\u00a3",   # £
    "yen": "\u00a5",      # ¥
    "euro": "\u20ac",     # €
    "textregistered": "\u00ae",
    "texttrademark": "\u2122",
    "textcopyright": "\u00a9",
    "textdegree": "\u00b0",
    "LaTeX": "LaTeX",
    "TeX": "TeX",
}


def normalize_latex_text(text: str) -> str:
    """Convert LaTeX typographic conventions in plain text to Unicode.

    Handles: ``...'' quotes, --/--- dashes.
    Single quote replacement (' -> right quote) is NOT done to avoid
    breaking apostrophes.
    """
    # Order matters: --- before --, `` before `
    text = text.replace("---", "\u2014")
    text = text.replace("--", "\u2013")
    text = text.replace("``", "\u201c")
    text = text.replace("''", "\u201d")
    return text
