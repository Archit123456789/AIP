"""Human-review surface (Step 6): flagged issues -> self-contained HTML page or interactive CLI.

  python -m aip.review --issues results/hybrid.jsonl --html results/review.html
  python -m aip.review --issues results/hybrid.jsonl --cli --decisions results/decisions.jsonl

The system never acts on an issue: it only flags. A reviewer accepts (real issue), rejects (false alarm) or
marks unsure; decisions are exported as JSONL {issue_id, decision, note, ts} and can be fed back to measure precision
in production or to build a labelled set.
"""
from __future__ import annotations

import argparse
import html
import json
import time
from pathlib import Path

from .schema import load_predictions, load_records, ISSUE_TYPES

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Data-Quality Review</title><style>
:root{--bg:#fff;--fg:#1b1f24;--mut:#667085;--line:#e4e7ec;--card:#f9fafb;--ok:#067647;--bad:#b42318;--unsure:#b54708;--acc:#175cd3}
@media(prefers-color-scheme:dark){:root{--bg:#0e1116;--fg:#e6e8eb;--mut:#98a2b3;--line:#2a2f37;--card:#161b22;--ok:#47cd89;--bad:#f97066;--unsure:#fdb022;--acc:#84adff}}
body{font:14px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg);margin:0 auto;max-width:1000px;padding:16px}
h1{font-size:20px;margin:0 0 4px}.sub{color:var(--mut);margin-bottom:12px}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:12px 0;position:sticky;top:0;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--line)}
.card{border:1px solid var(--line);background:var(--card);border-radius:8px;padding:10px 12px;margin:8px 0}
.card.accepted{border-left:4px solid var(--ok)}.card.rejected{border-left:4px solid var(--bad)}.card.unsure{border-left:4px solid var(--unsure)}
.tag{display:inline-block;font-size:12px;padding:1px 8px;border-radius:99px;border:1px solid var(--line);margin-right:6px;color:var(--mut)}
.t-duplicate,.t-contradiction{color:var(--bad)}.t-missing,.t-temporal{color:var(--unsure)}.t-terminology{color:var(--acc)}
button{font:inherit;border:1px solid var(--line);background:var(--bg);color:var(--fg);border-radius:6px;padding:3px 10px;cursor:pointer}
button.on{outline:2px solid var(--acc)}details{margin-top:6px}pre{white-space:pre-wrap;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:8px;font-size:12px;overflow-x:auto}
.mut{color:var(--mut)}input[type=text]{font:inherit;padding:3px 6px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
</style></head><body>
<h1>Data-quality review</h1>
<div class="sub">__SUB__ &middot; Flags only &mdash; nothing here is a clinical decision. Decisions are kept in this browser until exported.</div>
<div class="bar"><span id="filters"></span><label><input type="checkbox" id="pending"> pending only</label>
<span id="stats" class="mut"></span><button id="export">Export decisions (JSONL)</button></div>
<div id="list"></div>
<script>
const ISSUES=__ISSUES__, RECORDS=__RECORDS__, TYPES=__TYPES__;
const KEY="aip-review-decisions:"+__RUNID__;
let D={};try{D=JSON.parse(localStorage.getItem(KEY)||"{}")}catch(e){}
const save=()=>{try{localStorage.setItem(KEY,JSON.stringify(D))}catch(e){}};
const active=new Set(TYPES.filter(t=>t!=="terminology"));
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function render(){
  const pend=document.getElementById("pending").checked;
  const rows=ISSUES.filter(i=>active.has(i.issue_type)&&(!pend||!D[i.issue_id]));
  document.getElementById("list").innerHTML=rows.slice(0,400).map(i=>{
    const d=D[i.issue_id]||{};const cls=d.decision||"";
    return `<div class="card ${cls}" data-id="${esc(i.issue_id)}"><div><span class="tag t-${esc(i.issue_type)}">${esc(i.issue_type)}</span>
    <span class="tag">${esc(i.field_path)}</span><span class="tag">${esc(i.detector)}</span><span class="tag">conf ${(+i.confidence).toFixed(2)}</span>
    <span class="mut">${esc(i.record_ids.join(", "))}</span></div>
    <div><b>${esc(i.explanation||i.description)}</b></div>
    ${i.explanation&&i.explanation!==i.description?`<div class="mut">${esc(i.description)}</div>`:""}
    <details><summary>Evidence &amp; source records</summary><pre>${esc(JSON.stringify(i.evidence,null,1))}</pre>
    <pre>${i.record_ids.map(r=>esc(JSON.stringify(RECORDS[r],null,1))).join("\\n---\\n")}</pre></details>
    <div style="margin-top:6px">${["accepted","rejected","unsure"].map(x=>`<button class="${cls===x?"on":""}" data-d="${x}">${x==="accepted"?"Accept (real issue)":x==="rejected"?"Reject (false alarm)":"Unsure"}</button>`).join(" ")}
    <input type="text" placeholder="note" value="${esc(d.note||"")}" data-note="1"></div></div>`}).join("")
    +(rows.length>400?`<p class="mut">Showing first 400 of ${rows.length}; use filters.</p>`:"");
  const n=Object.keys(D).length;document.getElementById("stats").textContent=`${rows.length} shown · ${n}/${ISSUES.length} reviewed`;
}
document.getElementById("filters").innerHTML=TYPES.map(t=>`<label><input type="checkbox" data-t="${t}" ${active.has(t)?"checked":""}> ${t} (${ISSUES.filter(i=>i.issue_type===t).length})</label>`).join(" ");
document.addEventListener("change",e=>{if(e.target.dataset.t){e.target.checked?active.add(e.target.dataset.t):active.delete(e.target.dataset.t);render()}if(e.target.id==="pending")render()});
document.addEventListener("click",e=>{const b=e.target.closest("button[data-d]");if(!b)return;const id=b.closest(".card").dataset.id;
  const note=b.closest(".card").querySelector("[data-note]").value;D[id]={decision:b.dataset.d,note,ts:new Date().toISOString()};save();render()});
document.addEventListener("input",e=>{if(e.target.dataset.note){const id=e.target.closest(".card").dataset.id;if(D[id]){D[id].note=e.target.value;save()}}});
document.getElementById("export").onclick=()=>{const txt=Object.entries(D).map(([id,v])=>JSON.stringify({issue_id:id,...v})).join("\\n");
  const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([txt],{type:"application/jsonl"}));a.download="decisions.jsonl";a.click()};
render();
</script></body></html>"""


def build_html(issues: list, records: dict, run_id: str) -> str:
    order = {t: i for i, t in enumerate(("duplicate", "contradiction", "temporal", "missing", "terminology"))}
    issues = sorted(issues, key=lambda i: (order.get(i.issue_type, 9), i.confidence, i.issue_id))
    used = {r for i in issues for r in i.record_ids}
    recs = {rid: records[rid].to_dict() for rid in used if rid in records}
    data = json.dumps([i.to_dict() for i in issues]).replace("</", "<\\/")
    counts = ", ".join(f"{sum(i.issue_type == t for i in issues)} {t}" for t in ISSUE_TYPES)
    return (PAGE.replace("__ISSUES__", data).replace("__RECORDS__", json.dumps(recs).replace("</", "<\\/"))
            .replace("__TYPES__", json.dumps(list(ISSUE_TYPES))).replace("__RUNID__", json.dumps(run_id))
            .replace("__SUB__", html.escape(f"{len(issues)} flagged issues ({counts})")))


def cli_review(issues: list, records: dict, decisions_path: Path, types=None) -> None:
    done = {}
    if decisions_path.exists():
        done = {json.loads(l)["issue_id"]: json.loads(l) for l in decisions_path.read_text().splitlines() if l.strip()}
    todo = [i for i in issues if i.issue_id not in done and (not types or i.issue_type in types)]
    print(f"{len(todo)} issues to review ({len(done)} already decided). [a]ccept / [r]eject / [u]nsure / [s]kip / [q]uit")
    for n, i in enumerate(todo, 1):
        print(f"\n--- {n}/{len(todo)}  {i.issue_id}  {i.issue_type}  {i.field_path}  ({i.detector}, conf {i.confidence:.2f})")
        print(i.explanation or i.description)
        for e in i.evidence[:4]:
            print(f"   evidence: {e.get('record_id')} {e.get('field')} = {str(e.get('value'))[:160]}")
        print(f"   records: {', '.join(i.record_ids)}")
        while True:
            c = input("> ").strip().lower()[:1]
            if c in ("a", "r", "u", "s", "q"):
                break
        if c == "q":
            break
        if c == "s":
            continue
        note = input("note (optional): ").strip()
        dec = {"issue_id": i.issue_id, "decision": {"a": "accepted", "r": "rejected", "u": "unsure"}[c], "note": note,
               "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with decisions_path.open("a") as f:
            f.write(json.dumps(dec) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", default="data/records.jsonl")
    ap.add_argument("--issues", default="results/hybrid.jsonl")
    ap.add_argument("--html", help="write a self-contained HTML review page here")
    ap.add_argument("--cli", action="store_true")
    ap.add_argument("--decisions", default="results/decisions.jsonl")
    ap.add_argument("--types", default="", help="comma list of issue types to review in the CLI (default all)")
    a = ap.parse_args(argv)
    records = {r.record_id: r for r in load_records(a.records)}
    issues = load_predictions(a.issues)
    if a.html:
        Path(a.html).parent.mkdir(parents=True, exist_ok=True)
        Path(a.html).write_text(build_html(issues, records, Path(a.issues).stem), encoding="utf-8")
        print(f"wrote {a.html} ({len(issues)} issues)")
    if a.cli:
        Path(a.decisions).parent.mkdir(parents=True, exist_ok=True)
        cli_review(issues, records, Path(a.decisions), set(filter(None, a.types.split(","))))
    if not a.html and not a.cli:
        ap.error("pass --html PATH and/or --cli")


if __name__ == "__main__":
    main()
