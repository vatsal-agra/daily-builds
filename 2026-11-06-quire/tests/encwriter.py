"""Test-only: write an AES-128 (V4/R4) encrypted PDF that keeps non-stream objects in object streams
and uses an xref stream — the combination pypdf cannot produce. poppler is the independent oracle."""
import hashlib, os, struct, zlib
from quire.crypt import PAD, rc4, aes_cbc_encrypt
from quire.objects import Name, Ref, PdfString, Stream
from quire.writer import ser


def _owner_entry(user, owner):
    k = hashlib.md5((owner + PAD)[:32]).digest()
    for _ in range(50):
        k = hashlib.md5(k).digest()
    k = k[:16]
    x = rc4(k, (user + PAD)[:32])
    for i in range(1, 20):
        x = rc4(bytes(b ^ i for b in k), x)
    return x


def encrypt_pdf(doc, user=b"u", owner=b"o", use_objstm=True, perms=-4):
    id0 = os.urandom(16)
    O = _owner_entry(user, owner)
    P = perms & 0xFFFFFFFF
    key = hashlib.md5((user + PAD)[:32] + O + struct.pack("<I", P) + id0).digest()
    for _ in range(50):
        key = hashlib.md5(key[:16]).digest()
    key = key[:16]
    x = rc4(key, hashlib.md5(PAD + id0).digest())
    for i in range(1, 20):
        x = rc4(bytes(b ^ i for b in key), x)
    U = x + os.urandom(16)

    def okey(n):
        return hashlib.md5(key + struct.pack("<I", n)[:3] + b"\0\0" + b"sAlT").digest()[:16]

    def aes(n, data):
        iv = os.urandom(16)
        return iv + aes_cbc_encrypt(okey(n), iv, data, pad=True)

    def enc_strings(o, n):
        if isinstance(o, PdfString):
            return PdfString(aes(n, bytes(o)))
        if isinstance(o, list):
            return [enc_strings(v, n) for v in o]
        if isinstance(o, dict):
            return {k: enc_strings(v, n) for k, v in o.items()}
        return o

    objs = {n: doc.get_object(n) for n, e in doc.xref.items() if e[0] != "f"}
    objs = {n: o for n, o in objs.items() if o is not None and not (isinstance(o, Stream) and o.dict.get("Type") in ("ObjStm", "XRef"))}
    nxt = max(objs) + 1
    out = bytearray(b"%PDF-1.6\n%\xe2\xe3\xcf\xd3\n")
    offs, in_stm = {}, {}
    plain = [n for n, o in objs.items() if not isinstance(o, Stream)]
    if use_objstm:
        for i in range(0, len(plain), 50):
            chunk = plain[i:i + 50]
            sn = nxt
            nxt += 1
            body, head = bytearray(), []
            for j, n in enumerate(chunk):
                head.append(b"%d %d" % (n, len(body)))
                body += ser(objs[n]) + b" "      # strings inside ObjStm are NOT separately encrypted
                in_stm[n] = (sn, j)
            hd = b" ".join(head) + b"\n"
            data = aes(sn, zlib.compress(hd + bytes(body)))
            offs[sn] = len(out)
            out += b"%d 0 obj\n" % sn + ser({"Type": Name("ObjStm"), "N": len(chunk), "First": len(hd), "Filter": Name("FlateDecode"), "Length": len(data)}) + b"\nstream\n" + data + b"\nendstream\nendobj\n"
    for n, o in sorted(objs.items()):
        if n in in_stm:
            continue
        offs[n] = len(out)
        out += b"%d 0 obj\n" % n
        if isinstance(o, Stream):
            d = enc_strings(dict(o.dict), n)
            raw = o.raw if o.dict.get("Type") == "XRef" else aes(n, o.raw)
            d["Length"] = len(raw)
            out += ser(d) + b"\nstream\n" + raw + b"\nendstream"
        else:
            out += ser(enc_strings(o, n))
        out += b"\nendobj\n"
    en = nxt
    nxt += 1
    offs[en] = len(out)
    enc = {"Filter": Name("Standard"), "V": 4, "R": 4, "Length": 128, "P": perms, "O": PdfString(O), "U": PdfString(U),
           "CF": {"StdCF": {"CFM": Name("AESV2"), "AuthEvent": Name("DocOpen"), "Length": 16}}, "StmF": Name("StdCF"), "StrF": Name("StdCF")}
    out += b"%d 0 obj\n" % en + ser(enc) + b"\nendobj\n"
    xn = nxt
    nxt += 1
    xpos = len(out)
    rows = bytearray()
    for i in range(nxt):
        if i == xn:
            rows += bytes([1]) + xpos.to_bytes(4, "big") + b"\0\0"
        elif i in in_stm:
            rows += bytes([2]) + in_stm[i][0].to_bytes(4, "big") + in_stm[i][1].to_bytes(2, "big")
        elif i in offs:
            rows += bytes([1]) + offs[i].to_bytes(4, "big") + b"\0\0"
        else:
            rows += bytes([0]) + b"\0\0\0\0" + b"\xff\xff"
    z = zlib.compress(bytes(rows))
    t = {"Type": Name("XRef"), "Size": nxt, "W": [1, 4, 2], "Root": doc.trailer["Root"], "Encrypt": Ref(en), "ID": [PdfString(id0), PdfString(id0)], "Filter": Name("FlateDecode"), "Length": len(z)}
    out += b"%d 0 obj\n" % xn + ser(t) + b"\nstream\n" + z + b"\nendstream\nendobj\nstartxref\n%d\n%%%%EOF\n" % xpos
    return bytes(out)
