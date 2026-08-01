#!/usr/bin/env python3
"""Command-line front end for Reflow.

    python3 cli.py render page.html [--css style.css] [--width 800] [-o out.png]
    python3 cli.py render page.html --dump-dom
    python3 cli.py render page.html --dump-layout
    python3 cli.py render page.html --dump-cascade
"""

import argparse
import sys

from reflow.browser import render_page


def _dump_layout(box, depth=0, out=None):
    out = out if out is not None else []
    pad = '  ' * depth
    if box.box_type == 'line':
        words = ' '.join(f['text'] for f in box.fragments)
        out.append(f'{pad}[line] x={box.x:.0f} y={box.y:.0f} w={box.content_width:.0f} '
                    f'h={box.content_height:.0f} "{words}"')
    else:
        tag = box.node.name if (box.node and box.node.node_type == 'element') else '#root'
        out.append(f'{pad}<{tag}> x={box.x:.0f} y={box.y:.0f} '
                    f'w={box.content_width:.0f} h={box.content_height:.0f} '
                    f'border_box=({box.border_box_width():.0f}x{box.border_box_height():.0f}) '
                    f'bg={box.background}')
    for child in box.children:
        _dump_layout(child, depth + 1, out)
    return out


def _dump_cascade(dom, styles, out=None):
    out = out if out is not None else []
    for node in _walk_elements(dom):
        st = styles.get(node)
        if st is None:
            continue
        props = ' '.join(f'{k}={v}' for k, v in sorted(st.properties.items())
                          if k in ('display', 'color', 'font-size', 'background-color', 'text-align'))
        attrs = ''.join(f' {k}="{v}"' for k, v in node.attrs.items())
        out.append(f'<{node.name}{attrs}> {{ {props} }}')
    return out


def _walk_elements(node):
    if node.node_type == 'element':
        yield node
    for child in node.children:
        yield from _walk_elements(child)


def cmd_render(args):
    html_text = open(args.html_file, encoding='utf-8').read()
    css_text = ''
    if args.css:
        css_text = open(args.css, encoding='utf-8').read()

    result = render_page(html_text, extra_css=css_text, viewport_width=args.width)

    if args.dump_dom:
        print(result.dom.to_debug_string())
    if args.dump_cascade:
        print('\n'.join(_dump_cascade(result.dom, result.styles)))
    if args.dump_layout:
        print('\n'.join(_dump_layout(result.layout_root)))

    if not (args.dump_dom or args.dump_cascade or args.dump_layout) or args.output:
        with open(args.output, 'wb') as f:
            f.write(result.png)
        print(f'wrote {args.output} '
              f'({result.canvas.width}x{result.canvas.height})', file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(prog='reflow', description='A from-scratch browser rendering engine.')
    sub = parser.add_subparsers(dest='command', required=True)

    render_cmd = sub.add_parser('render', help='render an HTML file to PNG (and/or dump pipeline stages)')
    render_cmd.add_argument('html_file')
    render_cmd.add_argument('--css', help='external CSS file to apply before the document\'s own <style> tags')
    render_cmd.add_argument('--width', type=int, default=800, help='viewport width in px (default: 800)')
    render_cmd.add_argument('-o', '--output', default='out.png', help='output PNG path (default: out.png)')
    render_cmd.add_argument('--dump-dom', action='store_true', help='print the parsed DOM tree')
    render_cmd.add_argument('--dump-cascade', action='store_true', help='print computed styles per element')
    render_cmd.add_argument('--dump-layout', action='store_true', help='print the positioned layout box tree')
    render_cmd.set_defaults(func=cmd_render)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
