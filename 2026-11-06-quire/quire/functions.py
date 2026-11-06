"""PDF function objects (types 0, 2, 3, 4)."""
import math
from .lexer import Lexer, Punct
from .objects import Stream, Keyword


class FunctionError(Exception):
    pass


def _interp(x, x0, x1, y0, y1):
    return y0 + (x - x0) * (y1 - y0) / (x1 - x0) if x1 != x0 else y0


class Function:
    def __init__(self, doc, obj):
        r = doc.resolve
        obj = r(obj)
        d = obj.dict if isinstance(obj, Stream) else obj
        if not isinstance(d, dict):
            raise FunctionError("not a function")
        self.type = r(d.get("FunctionType"))
        self.domain = [float(r(v)) for v in r(d.get("Domain")) or [0, 1]]
        rg = r(d.get("Range"))
        self.range = [float(r(v)) for v in rg] if rg else None
        self.n_in = len(self.domain) // 2
        t = self.type
        if t == 0:
            self.size = [int(r(v)) for v in r(d["Size"])]
            self.bps = int(r(d["BitsPerSample"]))
            self.encode = [float(r(v)) for v in r(d.get("Encode")) or sum(([0, s - 1] for s in self.size), [])]
            self.n_out = len(self.range) // 2
            self.decode = [float(r(v)) for v in r(d.get("Decode")) or self.range]
            data = doc.decode_stream(obj)
            total = self.n_out
            for s in self.size:
                total *= s
            bits = int.from_bytes(data, "big") if self.bps not in (8, 16, 32) else None
            self.samples = []
            if self.bps in (8, 16, 32):
                step = self.bps // 8
                for i in range(total):
                    chunk = data[i * step:(i + 1) * step]
                    self.samples.append(int.from_bytes(chunk, "big") if len(chunk) == step else 0)
            else:
                nb = len(data) * 8
                for i in range(total):
                    off = i * self.bps
                    if off + self.bps > nb:
                        self.samples.append(0)
                        continue
                    self.samples.append((bits >> (nb - off - self.bps)) & ((1 << self.bps) - 1))
        elif t == 2:
            self.c0 = [float(r(v)) for v in r(d.get("C0")) or [0.0]]
            self.c1 = [float(r(v)) for v in r(d.get("C1")) or [1.0]]
            self.N = float(r(d.get("N", 1)))
            self.n_out = len(self.c0)
        elif t == 3:
            self.funcs = [Function(doc, f) for f in r(d["Functions"])]
            self.bounds = [float(r(v)) for v in r(d.get("Bounds")) or []]
            self.encode = [float(r(v)) for v in r(d["Encode"])]
            self.n_out = self.funcs[0].n_out
        elif t == 4:
            self.prog = self._parse_ps(doc.decode_stream(obj))
            self.n_out = len(self.range) // 2
        else:
            raise FunctionError(f"unsupported function type {t}")

    @staticmethod
    def _parse_ps(data):
        lx = Lexer(data, 0)
        t = lx.next_token()
        if not (isinstance(t, Punct) and t == "{"):
            raise FunctionError("bad PostScript function")

        def block():
            out = []
            while True:
                t = lx.next_token()
                if t is None:
                    raise FunctionError("unterminated PostScript block")
                if isinstance(t, Punct) and t == "{":
                    out.append(block())
                elif isinstance(t, Punct) and t == "}":
                    return out
                else:
                    out.append(t)
        return block()

    def __call__(self, *args):
        x = [min(max(float(a), self.domain[2 * i]), self.domain[2 * i + 1]) for i, a in enumerate(args[:self.n_in])]
        t = self.type
        if t == 2:
            xv = x[0]
            try:
                p = xv ** self.N
            except (ZeroDivisionError, ValueError, OverflowError):
                p = 0.0
            y = [self.c0[i] + p * (self.c1[i] - self.c0[i]) for i in range(self.n_out)]
        elif t == 3:
            xv = x[0]
            k = 0
            while k < len(self.bounds) and xv >= self.bounds[k]:
                k += 1
            if k > len(self.funcs) - 1:
                k = len(self.funcs) - 1
            lo = self.domain[0] if k == 0 else self.bounds[k - 1]
            hi = self.domain[1] if k == len(self.bounds) else self.bounds[k]
            e0, e1 = self.encode[2 * k], self.encode[2 * k + 1]
            xe = _interp(xv, lo, hi, e0, e1)
            y = list(self.funcs[k](xe))
        elif t == 0:
            y = self._sampled(x)
        else:
            y = self._ps(x)
        if self.range:
            y = [min(max(v, self.range[2 * i]), self.range[2 * i + 1]) for i, v in enumerate(y)]
        return y

    def _sampled(self, x):
        m = self.n_in
        e = []
        for i in range(m):
            v = _interp(x[i], self.domain[2 * i], self.domain[2 * i + 1], self.encode[2 * i], self.encode[2 * i + 1])
            e.append(min(max(v, 0), self.size[i] - 1))
        out = []
        for j in range(self.n_out):
            # multilinear interpolation over 2^m corners
            acc = 0.0
            for corner in range(1 << m):
                wgt = 1.0
                idx = 0
                stride = 1
                for i in range(m):
                    f = int(math.floor(e[i]))
                    fr = e[i] - f
                    if corner >> i & 1:
                        f = min(f + 1, self.size[i] - 1)
                        wgt *= fr
                    else:
                        wgt *= 1 - fr
                    idx += f * stride
                    stride *= self.size[i]
                if wgt:
                    acc += wgt * self.samples[idx * self.n_out + j]
            dmax = (1 << self.bps) - 1
            out.append(_interp(acc, 0, dmax, self.decode[2 * j], self.decode[2 * j + 1]))
        return out

    def _ps(self, x):
        st = list(x)
        self._run(self.prog, st)
        n = self.n_out
        return [float(v) for v in st[-n:]] if n else []

    def _run(self, prog, st):
        i = 0
        while i < len(prog):
            t = prog[i]
            i += 1
            if isinstance(t, (int, float)) and not isinstance(t, bool):
                st.append(t)
            elif isinstance(t, list):
                nxt = prog[i] if i < len(prog) else None
                if nxt == "if":
                    i += 1
                    if st.pop():
                        self._run(t, st)
                elif isinstance(nxt, list) and i + 1 < len(prog) and prog[i + 1] == "ifelse":
                    i += 2
                    self._run(t if st.pop() else nxt, st)
            elif isinstance(t, Keyword):
                self._op(str(t), st)

    @staticmethod
    def _op(op, s):
        if op in ("add", "sub", "mul", "div", "idiv", "mod", "exp", "atan", "eq", "ne", "gt", "ge", "lt", "le",
                  "and", "or", "xor", "bitshift"):
            b, a = s.pop(), s.pop()
            if op == "add": s.append(a + b)
            elif op == "sub": s.append(a - b)
            elif op == "mul": s.append(a * b)
            elif op == "div": s.append(a / b if b else 0.0)
            elif op == "idiv": s.append(int(a) // int(b) if int(b) else 0)
            elif op == "mod": s.append(int(math.fmod(int(a), int(b))) if int(b) else 0)
            elif op == "exp":
                try: s.append(float(a) ** float(b))
                except (ValueError, ZeroDivisionError, OverflowError): s.append(0.0)
            elif op == "atan":
                v = math.degrees(math.atan2(a, b)); s.append(v + 360 if v < 0 else v)
            elif op == "eq": s.append(a == b)
            elif op == "ne": s.append(a != b)
            elif op == "gt": s.append(a > b)
            elif op == "ge": s.append(a >= b)
            elif op == "lt": s.append(a < b)
            elif op == "le": s.append(a <= b)
            elif op in ("and", "or", "xor"):
                if isinstance(a, bool) and isinstance(b, bool):
                    s.append({"and": a and b, "or": a or b, "xor": a != b}[op])
                else:
                    a, b = int(a), int(b)
                    s.append({"and": a & b, "or": a | b, "xor": a ^ b}[op])
            elif op == "bitshift": s.append(int(a) << int(b) if b >= 0 else int(a) >> -int(b))
        elif op == "abs": s.append(abs(s.pop()))
        elif op == "neg": s.append(-s.pop())
        elif op == "ceiling": s.append(math.ceil(s.pop()))
        elif op == "floor": s.append(math.floor(s.pop()))
        elif op == "round": s.append(math.floor(s.pop() + 0.5))
        elif op == "truncate": s.append(math.trunc(s.pop()))
        elif op == "sqrt": s.append(math.sqrt(max(s.pop(), 0)))
        elif op == "sin": s.append(math.sin(math.radians(s.pop())))
        elif op == "cos": s.append(math.cos(math.radians(s.pop())))
        elif op == "ln": v = s.pop(); s.append(math.log(v) if v > 0 else 0.0)
        elif op == "log": v = s.pop(); s.append(math.log10(v) if v > 0 else 0.0)
        elif op == "cvi": s.append(int(s.pop()))
        elif op == "cvr": s.append(float(s.pop()))
        elif op == "not":
            v = s.pop(); s.append((not v) if isinstance(v, bool) else ~int(v))
        elif op == "true": s.append(True)
        elif op == "false": s.append(False)
        elif op == "pop": s.pop()
        elif op == "exch": s[-1], s[-2] = s[-2], s[-1]
        elif op == "dup": s.append(s[-1])
        elif op == "copy":
            n = int(s.pop())
            if n > 0: s.extend(s[-n:])
        elif op == "index": n = int(s.pop()); s.append(s[-1 - n])
        elif op == "roll":
            j, n = int(s.pop()), int(s.pop())
            if n > 0:
                j %= n
                if j:
                    part = s[-n:]
                    s[-n:] = part[-j:] + part[:-j]
