import unittest

from casement.render import render
from tests.helpers import find_box


class TestPositioning(unittest.TestCase):
    def test_relative_offset_does_not_affect_siblings(self):
        css = ".a { position: relative; top: 20px; left: 10px; } .b {}"
        html = "<html><body><div class='a'>a</div><div class='b'>b</div></body></html>"
        r = render(html, extra_css=css, viewport_width=800)
        a = find_box(r.root_box, cls="a")
        b = find_box(r.root_box, cls="b")
        body = find_box(r.root_box, tag="body")
        # 'a' itself is visually offset...
        self.assertAlmostEqual(a.dims.x, body.dims.x + 10, places=2)
        self.assertAlmostEqual(a.dims.y, body.dims.y + 20, places=2)
        # ...but 'b' still flows as if 'a' had never moved (no 20px gap).
        self.assertAlmostEqual(b.dims.y, a.dims.y - 20 + a.dims.height, places=2)

    def test_absolute_positioned_relative_to_positioned_ancestor(self):
        css = (
            ".container { position: relative; width: 300px; height: 200px; } "
            ".child { position: absolute; top: 15px; left: 25px; width: 40px; height: 10px; }"
        )
        html = "<html><body><div class='container'><div class='child'>x</div></div></body></html>"
        r = render(html, extra_css=css, viewport_width=800)
        container = find_box(r.root_box, cls="container")
        child = find_box(r.root_box, cls="child")
        self.assertAlmostEqual(child.dims.x, container.dims.x + 25, places=2)
        self.assertAlmostEqual(child.dims.y, container.dims.y + 15, places=2)

    def test_absolute_positioned_removed_from_flow(self):
        css = ".container { position: relative; } .child { position: absolute; top: 0; left: 0; width: 40px; height: 500px; }"
        html = "<html><body><div class='container'><div class='child'>x</div></div><div class='after'>after</div></body></html>"
        r = render(html, extra_css=css, viewport_width=800)
        container = find_box(r.root_box, cls="container")
        after = find_box(r.root_box, cls="after")
        # The 500px-tall absolutely positioned child must not push 'after' down.
        self.assertAlmostEqual(after.dims.y, container.dims.y, delta=5.0)

    def test_absolute_without_positioned_ancestor_uses_viewport(self):
        css = ".child { position: absolute; top: 5px; left: 5px; width: 20px; height: 20px; }"
        html = "<html><body><div class='child'>x</div></body></html>"
        r = render(html, extra_css=css, viewport_width=800)
        child = find_box(r.root_box, cls="child")
        self.assertAlmostEqual(child.dims.x, 5, places=1)
        self.assertAlmostEqual(child.dims.y, 5, places=1)


if __name__ == "__main__":
    unittest.main()
