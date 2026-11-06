"""PDF serialisation: write a clean, decrypted copy of a Document (classic xref table, or
object streams + xref stream with compress=True)."""
import re
import zlib
from .objects import Name, Ref, PdfString, Stream, Keyword
from . import filters


def ser(o):
    if o is None:
        return b"null"
    if o is True:
        return b"true"
    if o is False:
        return b"false"
    if isinstance(o, Ref):
        return b"%d %d R" % (o.num, o.gen)
    if isinstance(o, Name):
        s = str(o).encode("utf-8")
        return b"/" + re.sub(rb"[^!-~]|[#()<>\[\]{}/%]", lambda m: b"#%02X" % m.group(0)[0], s)
    if isinstance(o, PdfString):
        return b"<" + bytes(o).hex().encode() + b">"
    if isinstance(o, Keyword):
        return str(o).encode()
    if isinstance(o, bool):
        return b"true" if o else b"false"
    if isinstance(o, int):
        return b"%d" % o
    if isinstance(o, float):
        s = ("%.6f" % o).rstrip("0").rstrip(".")
        return (s or "0").encode()
    if isinstance(o, list):
        return b"[" + b" ".join(ser(x) for x in o) + b"]"
    if isinstance(o, dict):
        return b"<<" + b" ".join(b"/" + ser(Name(k))[1:] + b" " + ser(v) for k, v in o.items()) + b">>"
    if isinstance(o, bytes):
        return b"<" + o.hex().encode() + b">"
    if isinstance(o, str):  # plain str values are names (the parser only yields Name/Keyword/str-for-names)
        return ser(Name(o))
    raise TypeError(f"cannot serialise {type(o)}")


def _stream_bytes(doc, stm):
    """Return (dict, payload) with encryption removed. Filters are kept as-is (raw bytes are already decrypted)."""
    return dict(stm.dict), stm.raw


def write_document(doc, compress=False, drop_encrypt=True):
    nums = sorted(n for n, e in doc.xref.items() if e[0] != "f")
    objs = {}
    for n in nums:
        o = doc.get_object(n)
        if o is None:
            continue
        objs[n] = o
    trailer = {k: v for k, v in doc.trailer.items() if k in ("Root", "Info", "ID")}
    if "Encrypt" in trailer or (drop_encrypt and doc.dec is not None):
        trailer.pop("Encrypt", None)
    enc_num = getattr(doc, "encrypt_num", None) if doc.dec is not None else None
    if enc_num is not None:
        objs.pop(enc_num, None)
    # drop object streams / xref streams (their contents are already exploded as plain objects)
    for n in list(objs):
        o = objs[n]
        if isinstance(o, Stream) and o.dict.get("Type") in ("ObjStm", "XRef"):
            del objs[n]
    out = bytearray(b"%PDF-" + (doc.version if doc.version != "?" else "1.7").encode() + b"\n%\xe2\xe3\xcf\xd3\n")
    size = (max(objs) if objs else 0) + 1
    offsets = {}
    in_stream = {}
    if compress:
        packable = [n for n, o in objs.items() if not isinstance(o, Stream)]
        for chunk_start in range(0, len(packable), 100):
            chunk = packable[chunk_start:chunk_start + 100]
            sn = size
            size += 1
            body = bytearray()
            head = []
            for i, n in enumerate(chunk):
                head.append(b"%d %d" % (n, len(body)))
                body += ser(objs[n]) + b"\n"
                in_stream[n] = (sn, i)
            hd = b" ".join(head) + b"\n"
            data = zlib.compress(hd + bytes(body))
            d = {"Type": Name("ObjStm"), "N": len(chunk), "First": len(hd), "Filter": Name("FlateDecode"), "Length": len(data)}
            offsets[sn] = len(out)
            out += b"%d 0 obj\n" % sn + ser(d) + b"\nstream\n" + data + b"\nendstream\nendobj\n"
    for n, o in sorted(objs.items()):
        if n in in_stream:
            continue
        offsets[n] = len(out)
        out += b"%d 0 obj\n" % n
        if isinstance(o, Stream):
            d = dict(o.dict)
            d["Length"] = len(o.raw)
            out += ser(d) + b"\nstream\n" + o.raw + b"\nendstream"
        else:
            out += ser(o)
        out += b"\nendobj\n"
    xref_pos = len(out)
    if compress:
        xn = size
        size += 1
        rows = bytearray()
        for i in range(size):
            if i == xn:
                rows += bytes([1]) + xref_pos.to_bytes(4, "big") + (0).to_bytes(2, "big")
            elif i in in_stream:
                rows += bytes([2]) + in_stream[i][0].to_bytes(4, "big") + in_stream[i][1].to_bytes(2, "big")
            elif i in offsets:
                rows += bytes([1]) + offsets[i].to_bytes(4, "big") + (0).to_bytes(2, "big")
            else:
                rows += bytes([0]) + (0).to_bytes(4, "big") + (65535).to_bytes(2, "big")
        data = zlib.compress(bytes(rows))
        d = dict(trailer)
        d.update({"Type": Name("XRef"), "Size": size, "W": [1, 4, 2], "Filter": Name("FlateDecode"), "Length": len(data)})
        out += b"%d 0 obj\n" % xn + ser(d) + b"\nstream\n" + data + b"\nendstream\nendobj\n"
    else:
        out += b"xref\n0 %d\n" % size
        out += b"0000000000 65535 f \n"
        for i in range(1, size):
            if i in offsets:
                out += b"%010d 00000 n \n" % offsets[i]
            else:
                out += b"0000000000 65535 f \n"
        t = dict(trailer)
        t["Size"] = size
        out += b"trailer\n" + ser(t) + b"\n"
    out += b"startxref\n%d\n%%%%EOF\n" % xref_pos
    return bytes(out)
