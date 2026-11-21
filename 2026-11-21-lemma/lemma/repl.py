"""Interactive prompt.  Enter commands; a `by` proof ends with a blank line."""
import sys
from .session import Session
from .syntax import Parser, LemmaError, lex

HELP = """Lemma REPL — type a command (def / theorem / inductive / #check / #eval / #print …).
  • multi-line input continues until the command is complete; a `by` proof ends with a blank line
  • :load FILE   load a .lm file      :names   list declarations      :axioms NAME   axioms used
  • :help        this text            :quit    leave
Examples:   #eval 6 * 7        #check add_comm        theorem t : 2 + 2 = 4 := by refl."""


def complete(sess, text):
    """Is `text` a complete command (or several)?  Incomplete = parse error at end of input."""
    try:
        p = Parser(text, sess.nota)
        while p.tok.kind != "eof":
            p.command()
        return True
    except LemmaError as e:
        if e.pos is not None:
            toks = lex(text, sess.nota.symbols())
            last = toks[-1]
            if e.pos == last.pos:                      # error exactly at EOF -> keep reading
                return False
        return True


def repl(inp=None, out=None):
    inp = inp or sys.stdin
    out = out or sys.stdout
    sess = Session()
    interactive = inp.isatty() if hasattr(inp, "isatty") else False
    print("Lemma — a small proof assistant.  :help for help, :quit to leave.", file=out)
    buf = []
    while True:
        if interactive:
            out.write("lemma> " if not buf else "   ...  ")
            out.flush()
        line = inp.readline()
        if not line:
            break
        line = line.rstrip("\n")
        if not buf and line.startswith(":"):
            cmd, _, arg = line[1:].partition(" ")
            if cmd in ("q", "quit", "exit"):
                break
            if cmd == "help":
                print(HELP, file=out)
            elif cmd == "load":
                try:
                    src = open(arg.strip(), encoding="utf-8").read()
                except OSError as e:
                    print(f"cannot read {arg.strip()}: {e}", file=out)
                    continue
                n0 = len(sess.errors)
                sess.out.clear()
                sess.run(src, arg.strip())
                print("\n".join(sess.out), file=out)
                print("\n".join(sess.errors[n0:]) or "loaded.", file=out)
            elif cmd == "names":
                print(", ".join(n for n in sess.k.order if not n.endswith((".rec_1", ".rec_2"))), file=out)
            elif cmd == "axioms":
                axs = sess.k.axioms_of(arg.strip()) if arg.strip() in sess.k.decls else None
                print("unknown name" if axs is None else (", ".join(axs) or "no axioms"), file=out)
            else:
                print(f"unknown meta-command :{cmd}", file=out)
            continue
        if not line.strip() and not buf:
            continue
        buf.append(line)
        text = "\n".join(buf)
        has_by = " by " in " " + text.replace("\n", " ") + " " or text.rstrip().endswith("by")
        if has_by and line.strip():
            continue                                      # proofs end with a blank line
        if not text.strip():
            buf = []
            continue
        if not complete(sess, text):
            continue
        n0 = len(sess.errors)
        sess.out.clear()
        sess.run(text, "<repl>")
        for l in sess.out:
            print(l, file=out)
        for e in sess.errors[n0:]:
            print(e, file=out)
        buf = []
    return 0


if __name__ == "__main__":
    sys.exit(repl())
