"""The Chromium differential oracle: renders the same page with Casement
and with a real browser, and diffs the computed border-box geometry of
every `data-cid`-tagged element.

Scope (see PLAN.md's honesty note): this compares *box-model geometry* --
positions and sizes of elements sized by explicit CSS (widths/heights,
flex layout) -- against a real browser, which is a genuinely independent
ground truth for the box model and flexbox algorithms. It is not a text-
rendering fidelity check: Casement's bitmap font has different metrics
than whatever font a real browser substitutes for `monospace` on this
machine, so an element sized by its *text content* (`width: auto` wrapping
prose) will legitimately disagree between the two engines without either
being "wrong" -- that disagreement is a font-metric difference, not a
layout bug. Test pages meant for this tool should size their elements
explicitly.
"""

import json
import os
import subprocess
import tempfile

from . import css_parser, html_parser, style
from .dom import Element
from .layout import build_document_box
from .render import _position_and_layout_root, assign_cids, collect_css, export_flat_boxes

_JS_PATH = os.path.join(os.path.dirname(__file__), "oracle_extract.js")


def _find_body(document):
    for child in document.children:
        if isinstance(child, Element) and child.tag == "html":
            for c in child.children:
                if isinstance(c, Element) and c.tag == "body":
                    return c
    for child in document.children:
        if isinstance(child, Element) and child.tag == "body":
            return child
    return None


def build_standalone_html(document, css_text):
    """A clean, self-contained HTML document (fresh <html><head><style>
    ...) wrapping the parsed document's body content, for feeding to the
    browser oracle regardless of how well-formed the original source was."""
    body = _find_body(document)
    if body is not None:
        inner = "".join(html_parser.serialize(c) for c in body.children)
    else:
        inner = "".join(
            html_parser.serialize(c) for c in document.children
            if not (isinstance(c, Element) and c.tag in ("head", "html"))
        )
    style_tag = f"<style>{css_text}</style>" if css_text else ""
    return f'<!DOCTYPE html><html><head><meta charset="utf-8">{style_tag}</head><body>{inner}</body></html>'


def _node_env():
    """Playwright is installed as a global npm package in this environment,
    not a local node_modules -- Node only finds it if NODE_PATH points at
    the global module directory."""
    env = dict(os.environ)
    if "CASEMENT_NODE_PATH" in env:
        global_modules = env["CASEMENT_NODE_PATH"]
    else:
        try:
            global_modules = subprocess.run(
                ["npm", "root", "-g"], capture_output=True, text=True, timeout=15,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            global_modules = ""
    if global_modules:
        existing = env.get("NODE_PATH", "")
        env["NODE_PATH"] = global_modules + (os.pathsep + existing if existing else "")
    return env


def run_chromium_extraction(standalone_html, viewport_width):
    with tempfile.TemporaryDirectory() as d:
        html_path = os.path.join(d, "page.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(standalone_html)
        node = os.environ.get("CASEMENT_NODE_BIN", "node")
        proc = subprocess.run(
            [node, _JS_PATH, html_path, str(viewport_width)],
            capture_output=True, text=True, timeout=60, env=_node_env(),
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Chromium oracle extraction failed: {proc.stderr.strip()}")
        return json.loads(proc.stdout)


class OracleDiff:
    def __init__(self, cid, tag, casement_rect, browser_rect):
        self.cid = cid
        self.tag = tag
        self.casement_rect = casement_rect
        self.browser_rect = browser_rect

    @property
    def dx(self):
        return self.casement_rect["x"] - self.browser_rect["x"]

    @property
    def dy(self):
        return self.casement_rect["y"] - self.browser_rect["y"]

    @property
    def dw(self):
        return self.casement_rect["width"] - self.browser_rect["width"]

    @property
    def dh(self):
        return self.casement_rect["height"] - self.browser_rect["height"]

    @property
    def max_abs_diff(self):
        return max(abs(self.dx), abs(self.dy), abs(self.dw), abs(self.dh))


def compare(html_text, extra_css="", viewport_width=800):
    """Render `html_text` with both Casement and headless Chromium, and
    return (diffs: list[OracleDiff], casement_png_bytes)."""
    document = html_parser.parse(html_text)
    assign_cids(document)
    css_text = collect_css(document, extra_css)
    sheet = css_parser.parse_stylesheet(css_text)
    style_map = style.compute_styles(document, sheet)
    root_box, root_absolutes = build_document_box(document, style_map)
    _position_and_layout_root(root_box, root_absolutes, viewport_width)

    flat = export_flat_boxes(root_box)
    casement_by_cid = {}
    for entry in flat:
        if entry["cid"] is None:
            continue
        bb = entry["dims"]["border_box"]
        # keep the outermost (first-built, i.e. the element's own box, not
        # a nested replaced/inline-block that happens to share a cid) --
        # in practice each cid is unique to one element already.
        casement_by_cid.setdefault(entry["cid"], {"x": bb["x"], "y": bb["y"], "width": bb["w"], "height": bb["h"], "tag": entry["tag"]})

    standalone_html = build_standalone_html(document, css_text)
    browser_rects = run_chromium_extraction(standalone_html, viewport_width)

    diffs = []
    for cid, browser_rect in browser_rects.items():
        casement_rect = casement_by_cid.get(cid)
        if casement_rect is None:
            continue
        diffs.append(OracleDiff(cid, browser_rect.get("tag", "?"), casement_rect, browser_rect))
    diffs.sort(key=lambda d: int(d.cid))
    return diffs
