import os, subprocess, unittest
from helpers import *


class CliTests(TmpCase):
    def write(self, name, text):
        with open(self.p(name), "w") as f:
            f.write(text)
        return self.p(name)

    def hello(self):
        return self.write("hello.s", ".intel_syntax noprefix\n.text\n.global _start\n_start:\n  mov eax,1\n  mov edi,1\n"
                          "  lea rsi,[rip+m]\n  mov edx,3\n  syscall\n  mov eax,60\n  mov edi,9\n  syscall\n.data\nm: .ascii \"ok\\n\"\n")

    def test_as_ld_run(self):
        s = self.hello()
        r = cli("as", s, "-o", self.p("h.o"))
        self.assertEqual(r.returncode, 0, r.stderr)
        r = cli("ld", self.p("h.o"), "-o", self.p("h"), "-Map", self.p("h.map"), "--report", self.p("h.html"), "-v")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("bytes, entry", r.stdout)
        p = subprocess.run([self.p("h")], capture_output=True)
        self.assertEqual((p.returncode, p.stdout), (9, b"ok\n"))
        mp = rfile(self.p("h.map")).decode()
        self.assertIn("Memory map:", mp)
        self.assertIn("h.o(.text)", mp)
        html = rfile(self.p("h.html")).decode()
        self.assertIn("<title>Ferrule link report", html)
        self.assertNotIn("http://", html.replace("http://www.w3.org", ""))      # self-contained

    def test_build_assembles_sources_directly(self):
        r = cli("build", self.hello(), "-o", self.p("b"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(subprocess.run([self.p("b")], capture_output=True).returncode, 9)

    def test_ar_create_list_extract_update(self):
        cli("as", self.hello(), "-o", self.p("hello.o"))
        self.write("two.s", ".intel_syntax noprefix\n.text\n.global two\ntwo: ret\n")
        cli("as", self.p("two.s"), "-o", self.p("two.o"))
        self.assertEqual(cli("ar", "crs", self.p("l.a"), self.p("hello.o")).returncode, 0)
        self.assertEqual(cli("ar", "crs", self.p("l.a"), self.p("two.o")).returncode, 0)      # appends, not overwrites
        self.assertEqual(cli("ar", "t", self.p("l.a")).stdout.split(), ["hello.o", "two.o"])
        os.mkdir(self.p("x"))
        cwd = os.getcwd()
        os.chdir(self.p("x"))
        try:
            self.assertEqual(cli("ar", "x", self.p("l.a"), "two.o").returncode, 0)
        finally:
            os.chdir(cwd)
        self.assertEqual(rfile(self.p("x/two.o")), rfile(self.p("two.o")))
        r = cli("ar", "crs", self.p("l.a"), self.p("hello.s"))
        self.assertNotEqual(r.returncode, 0)                                                    # non-ELF member rejected

    def test_lib_flag_keeps_command_line_order(self):
        self.write("lib.s", ".intel_syntax noprefix\n.text\n.global value\nvalue: mov eax, 3\nret\n")
        self.write("main.s", ".intel_syntax noprefix\n.text\n.global _start\n_start: call value\nmov edi, eax\nmov eax, 60\nsyscall\n")
        cli("as", self.p("lib.s"), "-o", self.p("lib.o"))
        cli("as", self.p("main.s"), "-o", self.p("main.o"))
        cli("ar", "crs", self.p("libv.a"), self.p("lib.o"))
        r = cli("ld", self.p("main.o"), f"-L{self.tmp}", "-lv", "-o", self.p("m"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(subprocess.run([self.p("m")]).returncode, 3)
        r = cli("ld", "-lv", self.p("main.o"), "-L", self.tmp, "-o", self.p("m2"))               # archive too early
        self.assertEqual(r.returncode, 1)
        self.assertIn("undefined reference to `value'", r.stderr)

    def test_dump_and_nm_on_object_archive_and_exe(self):
        cli("as", self.hello(), "-o", self.p("h.o"))
        cli("ar", "crs", self.p("l.a"), self.p("h.o"))
        cli("ld", self.p("h.o"), "-o", self.p("h"))
        d = cli("dump", self.p("h.o")).stdout
        self.assertIn("R_X86_64_PC32", d)
        self.assertIn(".text", d)
        self.assertIn("defines: _start", cli("dump", self.p("l.a")).stdout)
        self.assertIn("LOAD", cli("dump", self.p("h")).stdout)
        self.assertRegex(cli("nm", self.p("h")).stdout, r"[0-9a-f]{16} T _start")
        self.assertRegex(cli("nm", self.p("h.o")).stdout, r" T _start")
        self.assertIn("h.o:", cli("nm", self.p("l.a")).stdout)

    def test_errors_are_one_line_with_nonzero_exit_and_no_traceback(self):
        s = self.write("bad.s", ".text\nmov rax, [rbx*3]\n")
        cases = [("as", s), ("as", self.p("nope.s")), ("ld"), ("ld", self.p("nope.o")), ("ld", s), ("ld", "--bogus"),
                 ("ld", s, "--base", "abc"), ("ar", "t", self.p("nope.a")), ("dump", self.p("nope")), ("nm", s),
                 ("ld", "-lzzz")]
        for args in cases:
            args = (args,) if isinstance(args, str) else args
            with self.subTest(args=args):
                r = cli(*args)
                self.assertNotEqual(r.returncode, 0)
                self.assertNotIn("Traceback", r.stderr)
                self.assertIn("error", r.stderr.lower())
        r = cli("as", s)
        self.assertIn("bad.s:2:", r.stderr)
        self.assertIn("mov rax, [rbx*3]", r.stderr)             # offending source line echoed

    def test_help_and_version(self):
        self.assertIn("ferrule", cli("--version").stdout)
        self.assertIn("usage: ferrule ld", cli("ld", "--help").stdout)

    def test_gc_sections_flag_and_report_listing(self):
        self.write("g.s", ".intel_syntax noprefix\n.text\n.global _start\n_start: mov eax,60\nxor edi,edi\nsyscall\n"
                   ".section .text.dead,\"ax\"\ndead: ret\n")
        r = cli("build", self.p("g.s"), "-o", self.p("g"), "--gc-sections", "-Map", self.p("g.map"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(".text.dead", rfile(self.p("g.map")).decode().split("Discarded")[1])

    @need_gnu
    def test_crosscheck_against_gnu_ld(self):
        r = cli("crosscheck", self.hello())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("IDENTICAL", r.stdout)


if __name__ == "__main__":
    unittest.main()
