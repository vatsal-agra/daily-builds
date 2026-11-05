"""Shared helpers for the Ferrule test-suite."""
import os, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from ferrule.asm import assemble          # noqa: E402
from ferrule.link import link, Options    # noqa: E402
from ferrule.elf import ElfObject         # noqa: E402

HAVE = {t: shutil.which(t) is not None for t in ("gcc", "g++", "as", "ld", "ar", "nm", "readelf", "objdump", "objcopy")}
CFLAGS = ["-O2", "-ffreestanding", "-fno-pic", "-fno-pie", "-fno-stack-protector",
          "-fno-asynchronous-unwind-tables", "-fcommon", "-c"]

need_gcc = unittest.skipUnless(HAVE["gcc"], "gcc not available")
need_gnu = unittest.skipUnless(HAVE["as"] and HAVE["ld"], "GNU binutils not available")
need_readelf = unittest.skipUnless(HAVE["readelf"], "readelf not available")


def wfile(path, data):
    with open(path, "wb") as f:
        f.write(data)


def rfile(path):
    with open(path, "rb") as f:
        return f.read()


def asm_obj(src, name="t.s"):
    """Assemble source text (Intel syntax assumed) into an ElfObject."""
    return assemble(".intel_syntax noprefix\n" + src, name)


def asm_bytes(src):
    obj = asm_obj(".text\n" + src)
    return next(s for s in obj.sections if s.name == ".text").data


def roundtrip(obj):
    return ElfObject.parse(obj.to_bytes(), obj.name)


def run_exe(data, tmpdir, name="prog", timeout=10, stdin=b""):
    path = os.path.join(tmpdir, name)
    with open(path, "wb") as f:
        f.write(data)
    os.chmod(path, 0o755)
    p = subprocess.run([path], capture_output=True, timeout=timeout, input=stdin)
    return p.returncode, p.stdout


def gcc_compile(src, out, extra=(), lang_flags=()):
    cc = "g++" if src.endswith((".cpp", ".cc")) else "gcc"
    subprocess.run([cc, *CFLAGS, *extra, src, "-o", out], check=True, capture_output=True)


def cli(*args):
    """Run `python3 -m ferrule ...`; returns CompletedProcess."""
    env = dict(os.environ, PYTHONPATH=ROOT)
    return subprocess.run([sys.executable, "-m", "ferrule", *args], capture_output=True, text=True, env=env)


class TmpCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def p(self, name):
        return os.path.join(self.tmp, name)


START = """
.global _start
_start:
    call main
    mov edi, eax
    mov eax, 60
    syscall
"""

WRITE_FN = """
.global sys_write
sys_write:
    mov eax, 1
    syscall
    ret
"""
