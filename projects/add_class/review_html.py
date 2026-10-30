"""A review page for a QS file: rows grouped by class, with the first sentence and links; reject by ticking.

  python review_html.py QS_FILE [--wiki en] [--out PAGE.html]
  -> PAGE.html (default: next to QS_FILE). Open it in a browser, tick the wrong rows, then 'Copy approved QS'
     (or 'Copy rejected') puts the lines on the clipboard for QuickStatements. Ticks are kept in the browser.
"""
import argparse
import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify_stub import class_names, first_sentence  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>QS review</title>
<style>
:root { --bg: #fff; --fg: #1d2125; --muted: #6b7280; --line: #e5e7eb; --head: #f3f4f6; --link: #0b63c4;
        --bad: #fde2e2; --badfg: #9b1c1c; }
@media (prefers-color-scheme: dark) { :root { --bg: #111418; --fg: #e6e8eb; --muted: #9aa3ad; --line: #2a3038;
        --head: #1a1f25; --link: #6cb6ff; --bad: #3b1d1d; --badfg: #ffb4b4; } }
body { background: var(--bg); color: var(--fg); font: 14px/1.4 system-ui, sans-serif; margin: 0 16px 80px; }
header { position: sticky; top: 0; background: var(--bg); padding: 10px 0; border-bottom: 1px solid var(--line);
         display: flex; gap: 12px; align-items: center; flex-wrap: wrap; z-index: 2; }
header input[type=search] { padding: 5px 8px; min-width: 260px; }
button { padding: 5px 10px; cursor: pointer; }
#stats { color: var(--muted); }
details { border: 1px solid var(--line); border-radius: 6px; margin: 10px 0; }
summary { background: var(--head); padding: 6px 10px; cursor: pointer; font-weight: 600; }
summary .n { color: var(--muted); font-weight: 400; }
table { border-collapse: collapse; width: 100%; }
td { border-top: 1px solid var(--line); padding: 4px 8px; vertical-align: top; }
td.c { width: 22px; } td.q { white-space: nowrap; width: 1%; } td.t { width: 22%; }
td.s { color: var(--fg); }
tr.bad td { background: var(--bad); } tr.bad td.s { color: var(--badfg); text-decoration: line-through; }
a { color: var(--link); text-decoration: none; } a:hover { text-decoration: underline; }
.hide { display: none; }
</style></head><body>
<header>
  <strong>__TITLE__</strong>
  <input type="search" id="f" placeholder="Filter (class, title, sentence)">
  <button id="open">Expand all</button><button id="close">Collapse all</button>
  <button id="ok">Copy approved QS</button><button id="no">Copy rejected</button>
  <span id="stats"></span>
</header>
<main id="m"></main>
<script>
const DATA = __DATA__, WIKI = "__WIKI__", KEY = "qsreview:" + "__TITLE__";
let bad = new Set();
try { bad = new Set(JSON.parse(localStorage.getItem(KEY) || "[]")); } catch (e) {}
const save = () => { try { localStorage.setItem(KEY, JSON.stringify([...bad])); } catch (e) {} stats(); };
const esc = s => s.replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const groups = {};
DATA.rows.forEach(r => (groups[r[1] + " " + r[2]] ||= []).push(r));
const m = document.getElementById("m");
Object.keys(groups).sort((a, b) => groups[b].length - groups[a].length).forEach(g => {
  const [p, c] = g.split(" "), rows = groups[g];
  const d = document.createElement("details");
  d.innerHTML = `<summary>${p} <a href="https://www.wikidata.org/wiki/${c}" target="_blank">${esc(DATA.label[c] || c)}</a>
    <span class="n">(${c}, ${rows.length})</span></summary><table>${rows.map(r =>
    `<tr data-k="${r[0]}\t${r[1]}\t${r[2]}"><td class="c"><input type="checkbox" title="reject"></td>
     <td class="q"><a href="https://www.wikidata.org/wiki/${r[0]}" target="_blank">${r[0]}</a></td>
     <td class="t"><a href="https://${WIKI}.wikipedia.org/wiki/${encodeURIComponent(r[3].replace(/ /g, "_"))}"
       target="_blank">${esc(r[3])}</a></td><td class="s">${esc(r[4])}</td></tr>`).join("")}</table>`;
  m.appendChild(d);
});
document.querySelectorAll("tr[data-k]").forEach(tr => {
  const cb = tr.querySelector("input"), k = tr.dataset.k;
  if (bad.has(k)) { cb.checked = true; tr.classList.add("bad"); }
  cb.onchange = () => { cb.checked ? bad.add(k) : bad.delete(k); tr.classList.toggle("bad", cb.checked); save(); };
});
function stats() { document.getElementById("stats").textContent =
  `${DATA.rows.length} rows, ${bad.size} rejected, ${DATA.rows.length - bad.size} approved`; }
stats();
document.getElementById("f").oninput = e => {
  const t = e.target.value.toLowerCase();
  document.querySelectorAll("details").forEach(d => {
    let any = false;
    d.querySelectorAll("tr").forEach(tr => {
      const hit = !t || d.querySelector("summary").textContent.toLowerCase().includes(t) ||
                  tr.textContent.toLowerCase().includes(t);
      tr.classList.toggle("hide", !hit); any ||= hit; });
    d.classList.toggle("hide", !any); if (t && any) d.open = true; });
};
document.getElementById("open").onclick = () => document.querySelectorAll("details").forEach(d => d.open = true);
document.getElementById("close").onclick = () => document.querySelectorAll("details").forEach(d => d.open = false);
const copy = (lines, what) => navigator.clipboard.writeText(lines.join("\\n") + "\\n")
  .then(() => alert(`${lines.length} ${what} lines copied`));
document.getElementById("ok").onclick = () =>
  copy(DATA.rows.map(r => r.slice(0, 3).join("\\t")).filter(k => !bad.has(k)), "approved");
document.getElementById("no").onclick = () => copy([...bad], "rejected");
</script></body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("qs")
    ap.add_argument("--wiki", default="en")
    ap.add_argument("--out")
    args = ap.parse_args()
    with open(args.qs, encoding="utf-8") as fh:
        rows = [line.rstrip("\n").split("\t")[:3] for line in fh if line.strip()]
    want = {q for q, _, _ in rows}
    with open(os.path.join(OUT, f"items_{args.wiki}.tsv"), encoding="utf-8") as fh:
        title = {q: t for q, t in (line.rstrip("\n").split("\t", 1) for line in fh if "\t" in line) if q in want}
    opening = {}
    with open(os.path.join(OUT, f"opening_{args.wiki}.tsv"), encoding="utf-8") as fh:
        for line in fh:
            q, t = line.rstrip("\n").split("\t", 1)
            if q in want:
                opening[q] = first_sentence(t)[:300]
    label = {c: v[0] for c, v in class_names(sorted({c for _, _, c in rows})).items()}
    data = {"label": label, "rows": [[q, p, c, title.get(q, ""), opening.get(q, "")] for q, p, c in rows]}
    out = args.out or os.path.splitext(args.qs)[0] + "_review.html"
    name = html.escape(os.path.basename(args.qs))
    page = (PAGE.replace("__TITLE__", name).replace("__WIKI__", args.wiki)
            .replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")))
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(page)
    print(f"{len(rows)} rows -> {out}")


if __name__ == "__main__":
    main()
