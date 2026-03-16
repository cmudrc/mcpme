"""Sphinx configuration for the mcpme documentation."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from sphinx.application import Sphinx

autoclass_content = "both"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

project = "mcpme"
copyright = "2026, mcpme contributors"
author = "mcpme contributors"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
]

napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_use_param = True
napoleon_use_rtype = False
autodoc_typehints = "none"
autosummary_generate = True
autosummary_imported_members = True
nitpicky = True

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# The docs site now has one supported presentation layer. Keeping the theme
# deterministic avoids branchy config and makes local builds match CI.
html_theme = "pydata_sphinx_theme"

html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_logo = "drc.png"
html_title = project
html_theme_options = {
    "logo": {
        "text": project,
    },
    "show_nav_level": 2,
    "navigation_depth": 2,
    "header_links_before_dropdown": 8,
    "secondary_sidebar_items": ["page-toc"],
    "icon_links": [
        {
            "name": "GitHub",
            "url": "https://github.com/cmudrc/mcpme",
            "icon": "fa-brands fa-github",
        }
    ],
}

_VIEWPORT_META_RE = re.compile(r'<meta name="viewport"[^>]*>', re.IGNORECASE)


def _dedupe_viewport_meta(
    app: object,
    pagename: str,
    templatename: str,
    context: dict[str, object],
    doctree: object,
) -> None:
    """Keep one viewport tag by removing extra entries from Sphinx metatags."""
    del app, pagename, templatename, doctree
    metatags = context.get("metatags")
    if isinstance(metatags, str):
        context["metatags"] = _VIEWPORT_META_RE.sub("", metatags)


def setup(app: Sphinx) -> None:
    """Register build-time hooks."""
    app.connect("html-page-context", _dedupe_viewport_meta)
