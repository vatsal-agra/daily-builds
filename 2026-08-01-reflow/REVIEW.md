# Adversarial review

Attacked the Phase 2 implementation as a hostile reviewer: fed it malformed
input, traced the math by hand, and looked for the kind of "looks plausible
in a happy-path demo but is actually wrong" bugs that don't show up unless
you specifically go looking. Found real bugs, all fixed below; a few
things are noted as accepted, documented limitations rather than bugs.

## Bugs found and fixed

1. **`AUTO_CLOSE` lookup direction was backwards (`html_parser.py`).** The
   dict content was right (`AUTO_CLOSE['p']` lists tags whose opening
   closes an open `<p>`) but the lookup checked `stack[-1].name in
   AUTO_CLOSE.get(name)` — i.e. keyed by the tag *being opened* instead of
   the tag *currently open*. Concretely: `<div><p>x</div>` closed the
   `<div>` the instant `<p>` opened, because `'div'` is in
   `AUTO_CLOSE['p']`. Every element after that landed as a sibling of
   `<div>` instead of a child. Fixed the lookup to
   `name in AUTO_CLOSE.get(stack[-1].name, ())`; verified with a full
   `to_debug_string()` dump showing correct nesting.

2. **Opening `<tr>` didn't close an open `<td>`.** `AUTO_CLOSE['td']` only
   listed `{'td', 'th'}`, so `<table><tr><td>1<td>2<tr><td>3</table>`
   produced the second `<tr>` nested *inside* the first row's cell instead
   of as a sibling row. Added `'tr'` to `AUTO_CLOSE['td']`/`['th']`; since
   the auto-close loop is a `while`, opening `<tr>` now pops the open
   `<td>` first, then sees the open `<tr>` underneath and pops that too.

3. **Headings, bold/italic tags, links, and lists had no default styling.**
   With no user-agent stylesheet, `<h1>` rendered at the same size as a
   `<p>` and lists had no indent — technically "the cascade works" but a
   page with zero CSS looked broken, which is a real, visible defect, not
   just a missing nice-to-have. Root cause of *why* a naive fix wouldn't
   have worked: property inheritance always wins over a tag-based default
   when there's no explicit declaration, so a per-tag fallback bolted onto
   `_initial_value()` would never actually fire on any element with a
   parent (i.e. almost every element). Fixed properly: added a real
   `UA_STYLESHEET` (`h1..h6` sizing/weight, `b`/`strong`, `i`/`em`, `a`
   color, `p`/`ul`/`ol` margins, list indent) parsed through the *same*
   cascade as author CSS, at the lowest source order — so it behaves
   exactly like a real browser's default stylesheet and any author rule
   of equal specificity still overrides it correctly.

4. **`font-size: em` didn't compound across nesting.** Discovered while
   building the UA-stylesheet fix above: `font-size` was resolved lazily,
   in the layout stage, always against a hardcoded 16px base — so two
   nested elements each declaring `font-size: 0.5em` both computed 8px
   instead of the second one compounding to 4px. Fixed by resolving
   `font-size` to an absolute px number *in the cascade*, using the
   parent's already-resolved size as the base, so it's computed once,
   correctly, in tree order. Verified: two levels of `0.5em` from a 20px
   base now yields 10px then 5px.

5. **`border: 1px solid rgb(0, 0, 0)` parsed the color as `"0)"`.** The
   shorthand expander split on whitespace with plain `.split()`, which
   shreds a comma-space color function into `rgb(0,` / `0,` / `0)`. Added
   a paren-depth-aware splitter (`_split_respecting_parens`) so a
   function-call token survives shorthand parsing intact.

6. **`<br>` did nothing at all.** It's a void element with no text, so it
   contributed zero tokens to inline layout and simply vanished — a very
   visible bug for anything but the simplest test page. Added a `BR`
   sentinel threaded through tokenizing/line-breaking/line-box-building so
   a `<br>` forces a new line (including a lone or doubled `<br>`
   producing a real blank line, not being silently dropped).

7. **Inline content right after a block sibling ignored that sibling's
   `margin-bottom`.** Margin collapsing is tracked as a *pending* value
   (`prev_margin_bottom`) applied lazily to whatever comes next, but the
   inline-run flush path positioned text at the raw cursor instead of
   `cursor + prev_margin_bottom` — so `<p style="margin-bottom:1em">...</p>`
   followed by bare inline content butted up against it with no gap,
   while the same margin correctly applied before a following *block*
   sibling. Fixed by applying the pending margin before laying out the
   run, same as the block path.

8. **Unquoted attribute value swallowed a trailing self-closing slash.**
   `<foo bar=baz/>` parsed `bar="baz/"` and never saw the `/>`, so the
   element wasn't self-closed and everything after nested inside it
   instead of becoming its sibling. Fixed the unquoted-value scan to stop
   before a `/` that's immediately followed by `>`, while still allowing
   ordinary internal slashes (`src=path/to/img.png` still parses as one
   value, unaffected — verified both cases explicitly).

9. **CLI always wrote `out.png`, even when only a `--dump-*` flag was
   requested.** Running `render page.html --dump-dom` cluttered the
   working directory with an unwanted `out.png` because the default
   output path was a truthy string, not an absence. Changed the default
   to `None` so a dump-only run writes nothing unless `-o` is given
   explicitly; a plain `render page.html` with no flags still defaults to
   `out.png` as before.

10. **Dead/misleading whitespace-stripping code in `_layout_flow_children`.**
    A block tried to special-case leading whitespace-only text nodes, but
    the condition it checked (`not child.data`, i.e. an empty string) can
    never be true for a real DOM text node — the tokenizer already drops
    empty text tokens before the tree is even built — so the branch was
    unreachable and the comment describing it was simply wrong about what
    the code did. Removed it; whitespace-only text already contributes
    zero words through the normal tokenizing path, so nothing was lost.

## Also added while reviewing (small, contained, not scope creep)

- `<img alt="...">` now renders its alt text (`[alt text]`) as a visible
  fallback, matching how a real browser shows alt text for an image it
  can't load — consistent with "no network image loading" being an
  explicit, stated non-goal, rather than images just silently vanishing.

## Verified robust, not changed

- Malformed CSS with a missing closing `}` (a rule's declaration text runs
  on and swallows subsequent rules as garbage property values) does not
  crash the parser — it produces a wrong/garbage value for that one
  property (which then fails color/length parsing gracefully and falls
  back to its initial value), and rendering continues. Confirmed with a
  stylesheet containing an unmatched brace, an `@media` block, and an
  unsupported attribute/pseudo-class selector all in the same input.
- Empty HTML input (`''`) renders a minimal 1px-tall page, not a crash.
- Mismatched inline tags (`<b><i>x</b>y</i>`) close correctly per the
  "end tag closes everything above it" rule, matching real browsers.
- `<style>`/`<script>` raw-text handling survives a `</div>` appearing
  inside a JS string literal.

## Known, accepted limitations (not bugs — out of scope per PLAN.md)

- `line-height` is parsed, cascaded, and inherited, but line spacing in
  the inline layout is always the bitmap font's fixed metric; the
  computed `line-height` value isn't consumed yet.
- `font-weight: bold` and `font-style: italic` are tracked through the
  cascade but the hand-authored stroke font has only one weight/style, so
  they don't currently change the glyph rendering.
- `box-sizing` is always content-box (the CSS default); `border-box` isn't
  supported.
- CSS pseudo-classes and attribute selectors (`:hover`, `[data-x]`) parse
  without crashing but never match anything, since the compound-selector
  grammar only covers type/class/id — consistent with PLAN.md's stated
  selector scope.
