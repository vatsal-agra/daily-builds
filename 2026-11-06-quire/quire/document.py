"""Document: cross-reference handling (tables, streams, object streams, incremental
updates, hybrids), reconstruction of damaged files, decryption, and the page tree."""
import re
from .lexer import Lexer, SyntaxErr
from .objects import Name, Ref, PdfString, Stream, Keyword
from . import filters
from .crypt import Decryptor, CryptError, WrongPassword  # noqa: F401


class PdfError(Exception):
    pass


class Document:
    def __init__(self, data, password=b""):
        if isinstance(data, str):
            with open(data, "rb") as f:
                data = f.read()
        k = data.find(b"%PDF-", 0, 1024)
        if k > 0:  # junk before the header: offsets are relative to the header (Acrobat's rule)
            data = data[k:]
        self.data = data
        self.xref = {}          # num -> ("n", offset, gen) | ("c", objstm_num, index)
        self.trailer = {}
        self.cache = {}
        self.dec = None
        self.repaired = False
        self.repair_reason = None
        self.warnings = []
        self._objstm_cache = {}
        self._resolving = set()
        self._password = password
        self.version = self._header_version()
        self._load()
        self._setup_encryption()

    # ---------------------------------------------------------------- load
    def _header_version(self):
        m = re.search(rb"%PDF-(\d\.\d)", self.data[:1024])
        return m.group(1).decode() if m else "?"

    def _load(self):
        try:
            self._read_xref_chain()
        except (PdfError, SyntaxErr, filters.FilterError, ValueError, IndexError, KeyError, TypeError) as e:
            self._reconstruct(f"{type(e).__name__}: {e}")
            return
        self._setup_encryption()  # wrong passwords propagate; must precede any object-stream read
        try:
            root = self._raw_get(self.trailer.get("Root"))
            if not isinstance(root, dict) or "Pages" not in root:
                raise PdfError("catalog missing or has no /Pages")
            if not isinstance(self._raw_get(root["Pages"]), dict):
                raise PdfError("page tree unreachable")
        except (PdfError, SyntaxErr, filters.FilterError, ValueError, IndexError, KeyError, TypeError) as e:
            self._reconstruct(f"{type(e).__name__}: {e}")

    def _setup_encryption(self):
        enc_ref = self.trailer.get("Encrypt")
        if enc_ref is None:
            return
        self.encrypt_num = enc_ref.num if isinstance(enc_ref, Ref) else None
        self._setup_encryption_inner()
        self._objstm_cache.clear()

    def _plain(self, v):
        v = self._raw_get(v)
        if isinstance(v, dict):
            return {k: self._plain(x) for k, x in v.items()}
        if isinstance(v, list):
            return [self._plain(x) for x in v]
        return v

    # ------------------------------------------------------------ xref read
    def _read_xref_chain(self):
        tail = self.data[-2048:]
        m = list(re.finditer(rb"startxref\s+(\d+)", tail))
        if not m:
            raise PdfError("no startxref")
        pos = int(m[-1].group(1))
        seen = set()
        first = True
        queue = [pos]
        while queue:
            pos = queue.pop(0)
            if pos in seen:
                continue
            seen.add(pos)
            tr = self._read_xref_section(pos)
            if first:
                self.trailer = dict(tr)
                first = False
            else:
                for k, v in tr.items():
                    self.trailer.setdefault(k, v)
            if "XRefStm" in tr and isinstance(tr["XRefStm"], int):
                queue.insert(0, tr["XRefStm"])
            if isinstance(tr.get("Prev"), (int, float)):
                queue.append(int(tr["Prev"]))
        if "Root" not in self.trailer:
            raise PdfError("trailer has no /Root")

    def _read_xref_section(self, pos):
        d = self.data
        if pos < 0 or pos >= len(d):
            raise PdfError("xref offset out of range")
        lx = Lexer(d, pos)
        lx.skip_ws()
        if d.startswith(b"xref", lx.pos):
            return self._read_xref_table(lx)
        return self._read_xref_stream(lx.pos)

    def _read_xref_table(self, lx):
        lx.pos += 4
        d = self.data
        while True:
            lx.skip_ws()
            if d.startswith(b"trailer", lx.pos):
                lx.pos += 7
                break
            a = lx.next_token()
            b = lx.next_token()
            if not isinstance(a, int) or not isinstance(b, int):
                raise PdfError("bad xref subsection header")
            start = a
            for i in range(b):
                off = lx.next_token()
                gen = lx.next_token()
                kind = lx.next_token()
                if not isinstance(off, int) or not isinstance(gen, int) or kind not in ("n", "f"):
                    raise PdfError("bad xref entry")
                num = start + i
                if kind == "n" and num not in self.xref:
                    self.xref[num] = ("n", off, gen)
                elif kind == "f" and num not in self.xref:
                    self.xref[num] = ("f", 0, gen)
        tr = lx.parse_object()
        if not isinstance(tr, dict):
            raise PdfError("bad trailer")
        return tr

    def _read_xref_stream(self, pos):
        obj = self._parse_indirect_at(pos, None, decrypt=False)
        if not isinstance(obj, Stream) or obj.dict.get("Type") != "XRef":
            raise PdfError("expected xref stream")
        sd = obj.dict
        data = self.decode_stream(obj)
        w = [int(self._raw_get(x)) for x in self._raw_get(sd["W"])]
        size = int(self._raw_get(sd["Size"]))
        index = self._raw_get(sd.get("Index")) or [0, size]
        rl = sum(w)
        p = 0
        for i in range(0, len(index), 2):
            start, count = int(index[i]), int(index[i + 1])
            for j in range(count):
                if p + rl > len(data):
                    break
                f = []
                q = p
                for wi in w:
                    f.append(int.from_bytes(data[q:q + wi], "big"))
                    q += wi
                p += rl
                t = f[0] if w[0] else 1
                num = start + j
                if num in self.xref:
                    continue
                if t == 1:
                    self.xref[num] = ("n", f[1], f[2] if w[2] else 0)
                elif t == 2:
                    self.xref[num] = ("c", f[1], f[2] if w[2] else 0)
                else:
                    self.xref[num] = ("f", 0, 0)
        return sd

    # -------------------------------------------------------- object access
    def _parse_indirect_at(self, pos, expect_num, decrypt=True):
        d = self.data
        lx = Lexer(d, pos)
        n = lx.next_token()
        g = lx.next_token()
        kw = lx.next_token()
        if not (isinstance(n, int) and isinstance(g, int) and kw == "obj"):
            raise PdfError(f"no object header at {pos}")
        if expect_num is not None and n != expect_num:
            raise PdfError(f"object number mismatch at {pos}: wanted {expect_num}, found {n}")
        obj = lx.parse_object()
        save = lx.pos
        t = lx.next_token()
        if isinstance(t, Keyword) and t == "stream" and isinstance(obj, dict):
            p = lx.pos
            if d[p:p + 2] == b"\r\n":
                p += 2
            elif d[p:p + 1] in (b"\n", b"\r"):
                p += 1
            length = obj.get("Length")
            length = self._raw_get(length) if isinstance(length, Ref) else length
            raw = None
            if isinstance(length, int) and 0 <= length and p + length <= len(d):
                tail = d[p + length:p + length + 32].lstrip(b"\r\n \t")
                if tail.startswith(b"endstream") or tail.startswith(b"endobj"):
                    raw = d[p:p + length]
            if raw is None:
                e = d.find(b"endstream", p)
                if e < 0:
                    e = d.find(b"endobj", p)
                    if e < 0:
                        e = len(d)
                raw = d[p:e]
                if raw.endswith(b"\r\n"):
                    raw = raw[:-2]
                elif raw.endswith((b"\n", b"\r")):
                    raw = raw[:-1]
            obj = Stream(obj, raw)
        else:
            lx.pos = save
        if decrypt and self.dec is not None and n != getattr(self, "encrypt_num", None):
            obj = self._decrypt_obj(obj, n, g)
        return obj

    def _decrypt_obj(self, obj, num, gen):
        if isinstance(obj, PdfString):
            return PdfString(self.dec.decrypt_string(num, gen, bytes(obj)))
        if isinstance(obj, list):
            return [self._decrypt_obj(x, num, gen) for x in obj]
        if isinstance(obj, dict):
            return {k: self._decrypt_obj(v, num, gen) for k, v in obj.items()}
        if isinstance(obj, Stream):
            sd = self._decrypt_obj(obj.dict, num, gen)
            raw = self.dec.decrypt_stream(num, gen, obj.raw, sd)
            return Stream(sd, raw)
        return obj

    def _raw_get(self, x):
        """Resolve references (chains), no further processing."""
        n = 0
        while isinstance(x, Ref):
            x = self.get_object(x.num, x.gen)
            n += 1
            if n > 32:
                return None
        return x

    resolve = _raw_get

    def get_object(self, num, gen=0):
        if num in self.cache:
            return self.cache[num]
        ent = self.xref.get(num)
        if ent is None or ent[0] == "f":
            return None
        if num in self._resolving:
            return None
        self._resolving.add(num)
        try:
            try:
                if ent[0] == "n":
                    obj = self._parse_indirect_at(ent[1], num)
                else:
                    obj = self._from_objstm(ent[1], ent[2], num)
            except (PdfError, SyntaxErr, filters.FilterError, ValueError, IndexError):
                if not self.repaired:
                    self._reconstruct(f"object {num} unreadable")
                    self._resolving.discard(num)
                    return self.get_object(num, gen)
                obj = None
        finally:
            self._resolving.discard(num)
        self.cache[num] = obj
        return obj

    def _from_objstm(self, stm_num, idx, want):
        if stm_num not in self._objstm_cache:
            stm = self.get_object(stm_num)
            if not isinstance(stm, Stream):
                raise PdfError("object stream missing")
            data = self.decode_stream(stm)
            n = int(self._raw_get(stm.dict["N"]))
            first = int(self._raw_get(stm.dict["First"]))
            lx = Lexer(data, 0)
            pairs = []
            for _ in range(n):
                a, b = lx.next_token(), lx.next_token()
                pairs.append((a, b))
            self._objstm_cache[stm_num] = (data, first, pairs)
        data, first, pairs = self._objstm_cache[stm_num]
        if idx >= len(pairs) or pairs[idx][0] != want:
            for i, (nn, _) in enumerate(pairs):
                if nn == want:
                    idx = i
                    break
            else:
                raise PdfError("object not in its object stream")
        lx = Lexer(data, first + pairs[idx][1])
        return lx.parse_object()

    # ---------------------------------------------------------- stream data
    def decode_stream(self, stm, with_image=False):
        """Decoded bytes. With with_image=True returns (bytes, image_filter, parms)."""
        if stm._decoded is None:
            chain = filters.filter_chain(stm.dict, self._raw_get)
            stm._decoded = filters.decode_stream(stm.raw, chain)
        data, imgf, parm = stm._decoded
        return (data, imgf, parm) if with_image else data

    # ----------------------------------------------------- reconstruction
    def _reconstruct(self, reason):
        """Rebuild the xref by scanning the whole file for 'N G obj'."""
        self.repaired = True
        self.repair_reason = reason
        d = self.data
        self.cache.clear()
        self._objstm_cache.clear()
        self.xref = {}
        for m in re.finditer(rb"(?<![0-9])(\d{1,10})[ \t\r\n]+(\d{1,5})[ \t\r\n]+obj(?![a-zA-Z])", d):
            self.xref[int(m.group(1))] = ("n", m.start(1), int(m.group(2)))
        trailers = []
        for m in re.finditer(rb"trailer", d):
            try:
                t = Lexer(d, m.end()).parse_object()
                if isinstance(t, dict):
                    trailers.append(t)
            except Exception:  # noqa: BLE001
                pass
        # xref streams and object streams
        objstms = []
        for num, ent in list(self.xref.items()):
            pos = ent[1]
            head = d[pos:pos + 400]
            if b"/XRef" in head or b"/ObjStm" in head:
                try:
                    o = self._parse_indirect_at(pos, num, decrypt=False)
                except Exception:  # noqa: BLE001
                    continue
                if isinstance(o, Stream):
                    if o.dict.get("Type") == "XRef":
                        trailers.append(o.dict)
                    elif o.dict.get("Type") == "ObjStm":
                        objstms.append(num)
        self.trailer = {}
        for t in reversed(trailers):  # later trailers win
            for k in ("Root", "Encrypt", "ID", "Info"):
                if k in t and k not in self.trailer:
                    self.trailer[k] = t[k]
        self.dec = None
        # object streams: needs decryption first if encrypted, so set it up now
        if "Encrypt" in self.trailer:
            self.encrypt_num = self.trailer["Encrypt"].num if isinstance(self.trailer["Encrypt"], Ref) else None
            self._setup_encryption_inner()
        for sn in objstms:
            try:
                stm = self.get_object(sn)
                data = self.decode_stream(stm)
                n = int(self._raw_get(stm.dict["N"]))
                lx = Lexer(data, 0)
                for i in range(n):
                    a, _ = lx.next_token(), lx.next_token()
                    if isinstance(a, int) and (a not in self.xref):
                        self.xref[a] = ("c", sn, i)
            except Exception:  # noqa: BLE001
                continue
        if "Root" not in self.trailer or not isinstance(self._raw_get(self.trailer["Root"]), dict):
            for num in sorted(self.xref):
                o = self.get_object(num)
                if isinstance(o, dict) and o.get("Type") == "Catalog":
                    self.trailer["Root"] = Ref(num, 0)
            if "Root" not in self.trailer:
                raise PdfError("not a PDF file (or too damaged to recover): no document catalog found")
        self.warnings.append(f"xref reconstructed ({reason})")

    def _setup_encryption_inner(self):
        enc = self._raw_get(self.trailer["Encrypt"])
        if not isinstance(enc, dict):
            raise CryptError("/Encrypt does not point to a dictionary")
        enc = {k: self._plain(v) for k, v in enc.items()}
        ids = self._plain(self.trailer.get("ID")) or [b""]
        self.dec = Decryptor(enc, bytes(ids[0]) if ids and ids[0] is not None else b"", self._password)
        self.cache = {k: v for k, v in self.cache.items() if k == self.encrypt_num}

    # ----------------------------------------------------------- page tree
    @property
    def catalog(self):
        c = self._raw_get(self.trailer.get("Root"))
        return c if isinstance(c, dict) else {}

    @property
    def info(self):
        i = self._raw_get(self.trailer.get("Info"))
        return i if isinstance(i, dict) else {}

    def pages(self):
        """List of page dicts with inheritable attributes folded in."""
        out = []
        seen = set()
        inh = ("Resources", "MediaBox", "CropBox", "Rotate")

        def walk(node, inherited, depth=0):
            ref = node if isinstance(node, Ref) else None
            nd = self._raw_get(node)
            if not isinstance(nd, dict) or depth > 64:
                return
            if ref is not None:
                if ref.num in seen:
                    return
                seen.add(ref.num)
            cur = dict(inherited)
            for k in inh:
                if k in nd:
                    cur[k] = nd[k]
            kids = self._raw_get(nd.get("Kids"))
            if isinstance(kids, list) and nd.get("Type") != "Page":
                for k in kids:
                    walk(k, cur, depth + 1)
            else:
                p = dict(nd)
                for k, v in cur.items():
                    p.setdefault(k, v)
                p["_ref"] = ref
                out.append(p)

        walk(self.catalog.get("Pages"), {})
        if not out:  # damaged tree: fall back to scanning for /Type /Page
            for num in sorted(self.xref):
                o = self.get_object(num)
                if isinstance(o, dict) and o.get("Type") == "Page":
                    p = dict(o)
                    p["_ref"] = Ref(num, 0)
                    out.append(p)
        return out

    def page_content(self, page):
        c = self._raw_get(page.get("Contents"))
        parts = []
        items = c if isinstance(c, list) else [c]
        for it in items:
            s = self._raw_get(it)
            if isinstance(s, Stream):
                try:
                    parts.append(self.decode_stream(s))
                except filters.FilterError as e:
                    self.warnings.append(f"content stream undecodable: {e}")
        return b"\n".join(parts)

    def page_box(self, page, use_crop=True):
        def box(k):
            b = self._raw_get(page.get(k))
            if isinstance(b, list) and len(b) == 4:
                v = [self._raw_get(x) for x in b]
                if all(isinstance(x, (int, float)) for x in v):
                    return [min(v[0], v[2]), min(v[1], v[3]), max(v[0], v[2]), max(v[1], v[3])]
            return None
        mb = box("MediaBox") or [0, 0, 612, 792]
        cb = box("CropBox") if use_crop else None
        if cb:
            x0, y0 = max(mb[0], cb[0]), max(mb[1], cb[1])
            x1, y1 = min(mb[2], cb[2]), min(mb[3], cb[3])
            if x1 > x0 and y1 > y0:
                return [x0, y0, x1, y1]
        return mb

    def page_rotate(self, page):
        r = self._raw_get(page.get("Rotate")) or 0
        return int(r) % 360 if isinstance(r, (int, float)) else 0
