// Bundle the app into one standalone HTML file: node build.js  ->  dist/fathom.html
// The source modules use only single-line named imports/exports, which this bundler relies on.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const read = p => readFileSync(join(root, p), 'utf8');
const ORDER = ['src/rng.js', 'src/board.js', 'src/solver.js', 'src/generator.js', 'src/analysis.js', 'web/app.js'];

export function bundle() {
  let js = '';
  for (const f of ORDER) {
    const src = read(f);
    if (/^\s*import[\s{*][^;]*\n[^;]*from/m.test(src.replace(/^import .*;$/gm, ''))) throw new Error(`${f}: multi-line import not supported by the bundler`);
    const body = src
      .replace(/^import .*;\s*$/gm, '')
      .replace(/^export default /gm, '')
      .replace(/^export (?=(const|let|function|class|async))/gm, '');
    if (/^export /m.test(body)) throw new Error(`${f}: unsupported export form`);
    js += `\n// ---- ${f} ----\n${body}`;
  }
  const html = read('web/index.html')
    .replace('<link rel="stylesheet" href="style.css">\n', '')
    .replace('<!--INLINE_CSS-->', `<style>\n${read('web/style.css')}</style>`)
    .replace('<script type="module" src="app.js"></script>\n', '')
    .replace('<!--INLINE_JS-->', () => `<script type="module">${js}</script>`);
  return html;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const html = bundle();
  mkdirSync(join(root, 'dist'), { recursive: true });
  writeFileSync(join(root, 'dist/fathom.html'), html);
  console.log(`dist/fathom.html  ${(html.length / 1024).toFixed(0)} KB`);
}
