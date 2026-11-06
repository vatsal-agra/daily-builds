"""PDF standard security handler: RC4 (40/128), AES-128, AES-256 (R5 and R6).
Includes a from-scratch AES implementation (hashlib supplies MD5/SHA-2 only)."""
import hashlib
import struct

PAD = bytes.fromhex("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A")


# ---------------------------------------------------------------- RC4 ----
def rc4(key, data):
    S = list(range(256))
    j = 0
    kl = len(key)
    for i in range(256):
        j = (j + S[i] + key[i % kl]) & 255
        S[i], S[j] = S[j], S[i]
    out = bytearray(len(data))
    i = j = 0
    for n, b in enumerate(data):
        i = (i + 1) & 255
        j = (j + S[i]) & 255
        S[i], S[j] = S[j], S[i]
        out[n] = b ^ S[(S[i] + S[j]) & 255]
    return bytes(out)


# ---------------------------------------------------------------- AES ----
def _build_tables():
    sbox = [0] * 256
    p = q = 1
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ ((q << 1) | (q >> 7)) & 0xFF ^ ((q << 2) | (q >> 6)) & 0xFF ^ ((q << 3) | (q >> 5)) & 0xFF ^ ((q << 4) | (q >> 4)) & 0xFF
        sbox[p] = (x ^ 0x63) & 0xFF
        if p == 1:
            break
    sbox[0] = 0x63
    inv = [0] * 256
    for i, v in enumerate(sbox):
        inv[v] = i
    return sbox, inv


SBOX, INV_SBOX = _build_tables()


def _xt(a):
    a <<= 1
    return (a ^ 0x11B) & 0xFF if a & 0x100 else a


def _mul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xt(a)
        b >>= 1
    return r


_M2 = [_mul(i, 2) for i in range(256)]
_M3 = [_mul(i, 3) for i in range(256)]
_M9 = [_mul(i, 9) for i in range(256)]
_M11 = [_mul(i, 11) for i in range(256)]
_M13 = [_mul(i, 13) for i in range(256)]
_M14 = [_mul(i, 14) for i in range(256)]


def _expand_key(key):
    nk = len(key) // 4
    if len(key) not in (16, 24, 32):
        raise ValueError("bad AES key length")
    nr = nk + 6
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    rcon = 1
    for i in range(nk, 4 * (nr + 1)):
        t = list(w[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [SBOX[b] for b in t]
            t[0] ^= rcon
            rcon = _xt(rcon)
        elif nk > 6 and i % nk == 4:
            t = [SBOX[b] for b in t]
        w.append([w[i - nk][k] ^ t[k] for k in range(4)])
    return [sum((w[4 * r + c] for c in range(4)), []) for r in range(nr + 1)], nr


def _encrypt_block(rk, nr, blk):
    s = [blk[i] ^ rk[0][i] for i in range(16)]
    for r in range(1, nr + 1):
        s = [SBOX[b] for b in s]
        # shift rows (column-major state)
        s = [s[0], s[5], s[10], s[15], s[4], s[9], s[14], s[3], s[8], s[13], s[2], s[7], s[12], s[1], s[6], s[11]]
        if r != nr:
            t = []
            for c in range(0, 16, 4):
                a0, a1, a2, a3 = s[c:c + 4]
                t += [_M2[a0] ^ _M3[a1] ^ a2 ^ a3, a0 ^ _M2[a1] ^ _M3[a2] ^ a3,
                      a0 ^ a1 ^ _M2[a2] ^ _M3[a3], _M3[a0] ^ a1 ^ a2 ^ _M2[a3]]
            s = t
        k = rk[r]
        s = [s[i] ^ k[i] for i in range(16)]
    return bytes(s)


def _decrypt_block(rk, nr, blk):
    k = rk[nr]
    s = [blk[i] ^ k[i] for i in range(16)]
    for r in range(nr - 1, -1, -1):
        # inverse shift rows
        s = [s[0], s[13], s[10], s[7], s[4], s[1], s[14], s[11], s[8], s[5], s[2], s[15], s[12], s[9], s[6], s[3]]
        s = [INV_SBOX[b] for b in s]
        k = rk[r]
        s = [s[i] ^ k[i] for i in range(16)]
        if r:
            t = []
            for c in range(0, 16, 4):
                a0, a1, a2, a3 = s[c:c + 4]
                t += [_M14[a0] ^ _M11[a1] ^ _M13[a2] ^ _M9[a3], _M9[a0] ^ _M14[a1] ^ _M11[a2] ^ _M13[a3],
                      _M13[a0] ^ _M9[a1] ^ _M14[a2] ^ _M11[a3], _M11[a0] ^ _M13[a1] ^ _M9[a2] ^ _M14[a3]]
            s = t
    return bytes(s)


def aes_cbc_encrypt(key, iv, data, pad=False):
    if pad:
        n = 16 - len(data) % 16
        data += bytes([n]) * n
    if len(data) % 16:
        raise ValueError("data not block aligned")
    rk, nr = _expand_key(key)
    out = bytearray()
    prev = iv
    for i in range(0, len(data), 16):
        blk = bytes(a ^ b for a, b in zip(data[i:i + 16], prev))
        prev = _encrypt_block(rk, nr, blk)
        out += prev
    return bytes(out)


def aes_cbc_decrypt(key, iv, data, unpad=False):
    data = data[:len(data) - len(data) % 16]
    rk, nr = _expand_key(key)
    out = bytearray()
    prev = iv
    for i in range(0, len(data), 16):
        blk = data[i:i + 16]
        d = _decrypt_block(rk, nr, blk)
        out += bytes(a ^ b for a, b in zip(d, prev))
        prev = blk
    if unpad and out:
        n = out[-1]
        if 1 <= n <= 16 and all(b == n for b in out[-n:]):
            del out[-n:]
    return bytes(out)


def aes_ecb_encrypt(key, block):
    rk, nr = _expand_key(key)
    return _encrypt_block(rk, nr, block)


# ----------------------------------------------------- security handler ----
class CryptError(Exception):
    pass


class WrongPassword(CryptError):
    pass


def _hash_r6(password, salt, udata):
    k = hashlib.sha256(password + salt + udata).digest()
    i = 0
    while True:
        k1 = (password + k + udata) * 64
        e = aes_cbc_encrypt(k[:16], k[16:32], k1)
        mod = sum(e[:16]) % 3
        k = (hashlib.sha256, hashlib.sha384, hashlib.sha512)[mod](e).digest()
        i += 1
        if i >= 64 and e[-1] <= i - 32:
            break
    return k[:32]


class Decryptor:
    """Built from the /Encrypt dictionary (already resolved, strings as bytes)."""

    def __init__(self, enc, id0, password=b""):
        if enc.get("Filter") != "Standard":
            raise CryptError(f"unsupported security handler {enc.get('Filter')}")
        self.V = int(enc.get("V", 0))
        self.R = int(enc.get("R", 2))
        self.O = bytes(enc.get("O", b""))
        self.U = bytes(enc.get("U", b""))
        self.OE = bytes(enc.get("OE", b""))
        self.UE = bytes(enc.get("UE", b""))
        self.P = int(enc.get("P", 0)) & 0xFFFFFFFF
        self.id0 = id0
        self.encrypt_metadata = enc.get("EncryptMetadata", True) is not False
        self.length = int(enc.get("Length", 40)) // 8
        self.stm_method = self.str_method = "RC4"
        if self.V >= 4:
            cf = enc.get("CF") or {}
            self.stm_method = self._method(cf, enc.get("StmF", "Identity"))
            self.str_method = self._method(cf, enc.get("StrF", "Identity"))
            if self.V == 4:
                self.length = 16
        if self.V == 1:
            self.length = 5
        if self.R >= 5:
            self.length = 32
        if self.V not in (1, 2, 4, 5):
            raise CryptError(f"unsupported encryption V={self.V}")
        self.who = None
        self.key = None
        self.authenticate(password)

    @staticmethod
    def _method(cf, name):
        if name == "Identity":
            return "Identity"
        f = cf.get(str(name)) or {}
        cfm = str(f.get("CFM", "None"))
        return {"V2": "RC4", "AESV2": "AESV2", "AESV3": "AESV3", "None": "Identity"}.get(cfm, "Identity")

    # -- key derivation -----------------------------------------------------
    def _legacy_key(self, pw):
        pw = (pw + PAD)[:32]
        h = hashlib.md5(pw + self.O + struct.pack("<I", self.P) + self.id0)
        if self.R >= 4 and not self.encrypt_metadata:
            h.update(b"\xff\xff\xff\xff")
        k = h.digest()
        n = 5 if self.R == 2 else self.length
        if self.R >= 3:
            for _ in range(50):
                k = hashlib.md5(k[:n]).digest()
        return k[:n]

    def _check_user_legacy(self, key):
        if self.R == 2:
            return rc4(key, PAD) == self.U[:32]
        h = hashlib.md5(PAD + self.id0).digest()
        x = rc4(key, h)
        for i in range(1, 20):
            x = rc4(bytes(b ^ i for b in key), x)
        return x[:16] == self.U[:16]

    def _user_pw_from_owner(self, opw):
        opw = (opw + PAD)[:32]
        k = hashlib.md5(opw).digest()
        n = 5 if self.R == 2 else self.length
        if self.R >= 3:
            for _ in range(50):
                k = hashlib.md5(k).digest()
        k = k[:n]
        if self.R == 2:
            return rc4(k, self.O)
        x = self.O
        for i in range(19, -1, -1):
            x = rc4(bytes(b ^ i for b in k), x)
        return x

    def authenticate(self, password):
        pw = password if isinstance(password, bytes) else password.encode("utf-8")
        if self.R >= 5:
            return self._auth_v5(pw[:127])
        k = self._legacy_key(pw)
        if self._check_user_legacy(k):
            self.key, self.who = k, "user"
            return
        upw = self._user_pw_from_owner(pw)
        k = self._legacy_key(upw)
        if self._check_user_legacy(k):
            self.key, self.who = k, "owner"
            return
        raise WrongPassword("incorrect password")

    def _auth_v5(self, pw):
        h = _hash_r6 if self.R == 6 else (lambda p, s, u: hashlib.sha256(p + s + u).digest())
        O, U = self.O[:48], self.U[:48]
        # owner first (it also implies user rights)
        if h(pw, O[32:40], U) == O[:32]:
            ik = h(pw, O[40:48], U)
            self.key = aes_cbc_decrypt(ik, bytes(16), self.OE)
            self.who = "owner"
            return
        if h(pw, U[32:40], b"") == U[:32]:
            ik = h(pw, U[40:48], b"")
            self.key = aes_cbc_decrypt(ik, bytes(16), self.UE)
            self.who = "user"
            return
        raise WrongPassword("incorrect password")

    # -- per-object decryption ---------------------------------------------
    def _obj_key(self, num, gen, aes):
        if self.R >= 5:
            return self.key
        k = self.key + struct.pack("<I", num)[:3] + struct.pack("<I", gen)[:2]
        if aes:
            k += b"sAlT"
        return hashlib.md5(k).digest()[:min(len(self.key) + 5, 16)]

    def _run(self, method, num, gen, data):
        if method == "Identity":
            return data
        if method == "RC4":
            return rc4(self._obj_key(num, gen, False), data)
        key = self._obj_key(num, gen, True)
        if len(data) < 32 or len(data) % 16 not in (0,):
            if len(data) < 16:
                return b""
        return aes_cbc_decrypt(key, data[:16], data[16:], unpad=True)

    def decrypt_string(self, num, gen, data):
        return self._run(self.str_method, num, gen, data)

    def decrypt_stream(self, num, gen, data, sdict):
        t = sdict.get("Type")
        if t == "XRef":
            return data
        if t == "Metadata" and not self.encrypt_metadata:
            return data
        f = sdict.get("Filter")
        fl = f if isinstance(f, list) else [f]
        if "Crypt" in fl:
            dp = sdict.get("DecodeParms")
            dp = dp if isinstance(dp, list) else [dp]
            i = fl.index("Crypt")
            nm = (dp[i] or {}).get("Name", "Identity") if i < len(dp) and isinstance(dp[i], dict) else "Identity"
            if nm == "Identity":
                return data
        return self._run(self.stm_method, num, gen, data)

    PERMS = [(2, "print"), (3, "modify"), (4, "copy"), (5, "annotate"), (8, "fill forms"),
             (9, "accessibility"), (10, "assemble"), (11, "print high-res")]

    def permissions(self):
        p = self.P
        return {name: bool(p >> (bit - 1) & 1) for bit, name in self.PERMS}

    def describe(self):
        meth = {"RC4": f"RC4-{self.length * 8}", "AESV2": "AES-128", "AESV3": "AES-256"}
        m = meth.get(self.stm_method, "none") if self.V >= 4 else f"RC4-{self.length * 8}"
        return f"{m} (V{self.V} R{self.R}), opened as {self.who}"
