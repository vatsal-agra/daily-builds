"""Tiny PDF builder for tests: assemble arbitrary objects/streams into a valid file."""
import zlib
from quire.writer import ser
from quire.objects import Name, Ref, PdfString


class PB:
    def __init__(self, version="1.7"):
        self.objs = []          # (num, bytes body)
        self.version = version

    def add(self, obj=None, stream=None, compress=False, extra=None):
        """Add an object. If `stream` is given obj must be a dict (or None); returns Ref."""
        num = len(self.objs) + 1
        self.objs.append(None)
        self.set(num, obj, stream, compress, extra)
        return Ref(num)

    def reserve(self):
        self.objs.append(None)
        return Ref(len(self.objs))

    def set(self, num, obj=None, stream=None, compress=False, extra=None):
        if stream is not None:
            d = dict(obj or {})
            if compress:
                stream = zlib.compress(stream)
                d["Filter"] = Name("FlateDecode")
            d["Length"] = len(stream)
            body = ser(d) + b"\nstream\n" + stream + b"\nendstream"
        else:
            body = ser(obj)
        self.objs[num - 1] = body

    def page(self, content, resources=None, mediabox=(0, 0, 200, 200), extra=None, compress=False):
        pages_ref = Ref(len(self.objs) + 3)  # allocated below: content, page, pages
        c = self.add({}, stream=content if isinstance(content, bytes) else content.encode(), compress=compress)
        d = {"Type": Name("Page"), "Parent": pages_ref, "MediaBox": list(mediabox), "Contents": c,
             "Resources": resources or {}}
        d.update(extra or {})
        p = self.add(d)
        pages = self.add({"Type": Name("Pages"), "Kids": [p], "Count": 1})
        assert pages == pages_ref
        return self.finish(pages)

    def finish(self, pages, extra_catalog=None, trailer_extra=None):
        cat = {"Type": Name("Catalog"), "Pages": pages}
        cat.update(extra_catalog or {})
        root = self.add(cat)
        return self.build(root, trailer_extra)

    def build(self, root, trailer_extra=None):
        out = bytearray(b"%PDF-" + self.version.encode() + b"\n%\xe2\xe3\xcf\xd3\n")
        offs = []
        for i, body in enumerate(self.objs):
            offs.append(len(out))
            out += b"%d 0 obj\n" % (i + 1) + body + b"\nendobj\n"
        xr = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(self.objs) + 1)
        for o in offs:
            out += b"%010d 00000 n \n" % o
        t = {"Size": len(self.objs) + 1, "Root": root}
        t.update(trailer_extra or {})
        out += b"trailer\n" + ser(t) + b"\nstartxref\n%d\n%%%%EOF\n" % xr
        return bytes(out)


def std_font(name="Helvetica"):
    return {"Type": Name("Font"), "Subtype": Name("Type1"), "BaseFont": Name(name), "Encoding": Name("WinAnsiEncoding")}
