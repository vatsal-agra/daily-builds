"""Renders each pipeline stage as inspectable text/SVG for the interactive
viewer: the DOM tree, the CSSOM with specificity, a per-element cascade
explanation (which rule won and why), and an SVG diagram of the real
layout box tree with actual pixel coordinates/dimensions overlaid."""

from .css_parser import specificity


def _esc(text):
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def selector_to_str(steps):
    parts = []
    for combinator, compound in steps:
        if combinator == '>':
            parts.append('>')
        token = compound.type_name or '*'
        if compound.id:
            token += f'#{compound.id}'
        for cls in sorted(compound.classes):
            token += f'.{cls}'
        parts.append(token)
    return ' '.join(parts)


def dump_cssom_text(stylesheet):
    lines = []
    for rule in stylesheet.rules:
        selectors = ', '.join(selector_to_str(steps) for steps in rule.selectors)
        specs = [specificity(steps) for steps in rule.selectors]
        decls = '; '.join(
            f'{prop}: {value}{" !important" if important else ""}'
            for prop, (value, important) in rule.declarations.items()
        )
        lines.append(f'[order {rule.order:>3}] {selectors}  {{ specificity={specs} }}')
        lines.append(f'    {decls}')
    return '\n'.join(lines) if lines else '(no rules)'


_INTERESTING_PROPS = ('display', 'color', 'font-size', 'background-color', 'text-align', 'flex-direction')


def dump_cascade_text(document, styles):
    lines = []

    def walk(node):
        if node.node_type == 'element':
            style = styles.get(node)
            if style is not None:
                attrs = ''.join(f' {k}="{v}"' for k, v in node.attrs.items())
                lines.append(f'<{node.name}{attrs}>')
                if style.matches_debug:
                    for spec, order, steps in style.matches_debug:
                        lines.append(f'    matched  {selector_to_str(steps):<30} specificity={spec} order={order}')
                else:
                    lines.append('    matched  (nothing -- initial/inherited values only)')
                shown = {k: style.get(k) for k in _INTERESTING_PROPS}
                lines.append('    computed ' + ' '.join(f'{k}={v}' for k, v in shown.items()))
            for child in node.children:
                walk(child)
        else:
            for child in node.children:
                walk(child)

    walk(document)
    return '\n'.join(lines) if lines else '(empty document)'


_PALETTE = ['#e06c75', '#61afef', '#98c379', '#d19a66', '#c678dd', '#56b6c2', '#e5c07b']


def layout_to_svg(layout_root):
    width = max(1, int(round(layout_root.border_box_width())))
    height = max(1, int(round(layout_root.border_box_height())))
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="monospace" font-size="9">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>',
    ]
    _svg_box(layout_root, parts, depth=0)
    parts.append('</svg>')
    return '\n'.join(parts)


def _svg_box(box, parts, depth):
    if box.box_type == 'line':
        parts.append(
            f'<rect x="{box.x:.1f}" y="{box.y:.1f}" width="{box.content_width:.1f}" '
            f'height="{box.content_height:.1f}" fill="none" stroke="#3388ff" '
            f'stroke-width="0.5" stroke-dasharray="2,2"/>'
        )
        return
    color = _PALETTE[depth % len(_PALETTE)]
    bw = box.border_box_width()
    bh = box.border_box_height()
    tag = box.node.name if (box.node and box.node.node_type == 'element') else '#root'
    parts.append(
        f'<rect x="{box.x:.1f}" y="{box.y:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
        f'fill="none" stroke="{color}" stroke-width="1"/>'
    )
    label = _esc(f'{tag} {box.x:.0f},{box.y:.0f} {bw:.0f}x{bh:.0f}')
    # Nested boxes sharing a top-left corner (very common -- a margin-less
    # child starts exactly where its parent's padding box does) would
    # otherwise print overlapping, unreadable text. An opaque backing
    # rect behind each label means whichever box is drawn last (the
    # innermost, most specific one) is the one that stays legible.
    label_w = 5.4 * len(label) + 4
    parts.append(f'<rect x="{box.x + 1:.1f}" y="{box.y:.1f}" width="{label_w:.1f}" height="10" fill="white" fill-opacity="0.85"/>')
    parts.append(f'<text x="{box.x + 2:.1f}" y="{box.y + 9:.1f}" fill="{color}">{label}</text>')
    for child in box.children:
        _svg_box(child, parts, depth + 1)
