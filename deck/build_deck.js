// Builds the 4-slide deck. Numbers are copied from results/metrics.md, reports/lab6_redteam.md, results/rag_ceiling.md.
const pptxgen = require("pptxgenjs");
const { applyTheme } = require("/root/.claude/skills/synced/3ca01fc2-0c80-47f1-8bf6-8b12725a3df7_a0064ac4-6a95-4986-a36c-9565b27dec31/pptx/scripts/apply_theme.js");

const THEME = {
  name: "Clinical Teal", headFontFace: "Cambria", bodyFontFace: "Calibri",
  colors: { dk1: "1F2A30", lt1: "FFFFFF", dk2: "0B4F5C", lt2: "E8F3F1", accent1: "0B4F5C", accent2: "1C9C8C",
            accent3: "E4574A", accent4: "E8A93B", accent5: "5B7C99", accent6: "8FB8B0", hlink: "1C9C8C", folHlink: "5B7C99" },
};
const H = THEME.colors; // hex values for chart options (charts need hex)

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";            // 13.33 x 7.5
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "Healthcare Data-Quality Firewall";
const C = pres.SchemeColor;

pres.defineSlideMaster({
  title: "LIGHT_TITLE", background: { color: H.lt1 },
  slideNumber: { x: 12.35, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: C.text1 },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.35, w: 12.1, h: 0.85, fontSize: 36, bold: true,
                                          color: C.text2, valign: "middle", align: "left", margin: 0 }, text: "" } }],
});
pres.defineSlideMaster({
  title: "DARK_TITLE", background: { color: H.dk2 },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.5, w: 12.1, h: 0.9, fontSize: 40, bold: true,
                                          color: C.background1, valign: "middle", align: "left", margin: 0 }, text: "" } }],
});

const card = (slide, x, y, w, h, name, fill = C.background2) =>
  slide.addShape(pres.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.08, fill: { color: fill }, line: { color: fill, width: 0 }, objectName: name });
const txt = (slide, t, o) => slide.addText(t, Object.assign({ isTextBox: true, margin: 0, fontFace: THEME.bodyFontFace, color: C.text1 }, o));

// ------------------------------------------------------------------ slide 1: problem + approach
pres.addSection({ title: "Problem and approach" });
let s = pres.addSlide({ masterName: "DARK_TITLE", sectionTitle: "Problem and approach" });
s.addText("Healthcare Data-Quality Firewall", { placeholder: "title" });
txt(s, "Fragmented clinical records are checked before they reach downstream AI. Issues are flagged for human review; nothing here makes a clinical decision.",
    { x: 0.6, y: 1.5, w: 12.1, h: 0.8, fontSize: 18, color: C.background1, valign: "top" });
const stages = [
  ["1", "Labelled data", "300 synthetic patients, 1,033 fragmented records, 1,416 planted issues"],
  ["2", "Rules", "Patient linkage plus deterministic checks for all five issue types"],
  ["3", "Hybrid LLM", "Gemini only on the residual: unfamiliar terms, free-text notes, borderline duplicates"],
  ["4", "RAG", "Guideline and terminology knowledge base; answers must cite what was retrieved"],
  ["5", "Guarded agent", "Tool loop with budgets, human approval and a 21-case red-team suite"],
];
const cw = 2.35, gap = 0.1625, y0 = 2.65;
stages.forEach(([n, head, body], i) => {
  const x = 0.6 + i * (cw + gap);
  card(s, x, y0, cw, 3.1, `stage-card-${n}`, C.background1);
  s.addShape(pres.ShapeType.ellipse, { x: x + 0.2, y: y0 + 0.2, w: 0.55, h: 0.55, fill: { color: C.accent2 }, line: { color: C.accent2, width: 0 }, objectName: `stage-num-${n}` });
  txt(s, n, { x: x + 0.2, y: y0 + 0.2, w: 0.55, h: 0.55, fontSize: 20, bold: true, color: C.background1, align: "center", valign: "middle" });
  txt(s, head, { x: x + 0.2, y: y0 + 0.9, w: cw - 0.4, h: 0.65, fontSize: 18, bold: true, color: C.text2, valign: "top" });
  txt(s, body, { x: x + 0.2, y: y0 + 1.6, w: cw - 0.4, h: 1.4, fontSize: 14, valign: "top" });
});
txt(s, "Five issue types", { x: 0.6, y: 5.95, w: 3, h: 0.35, fontSize: 14, bold: true, color: C.accent6, valign: "middle" });
["Duplicates", "Contradictions", "Missing information", "Temporal errors", "Terminology drift"].forEach((t, i) => {
  const x = 0.6 + i * 2.5;
  s.addShape(pres.ShapeType.roundRect, { x, y: 6.35, w: 2.35, h: 0.5, rectRadius: 0.25, fill: { color: C.accent2 }, line: { color: C.accent2, width: 0 }, objectName: `issue-chip-${i + 1}` });
  txt(s, t, { x, y: 6.35, w: 2.35, h: 0.5, fontSize: 14, bold: true, color: C.background1, align: "center", valign: "middle" });
});
s.addNotes("Track: Healthcare. Problem: patient data is split across systems with different IDs, name formats and wording, and errors flow into clinical AI. Five issue types: duplicates, contradictions, missing information, temporal errors, terminology differences. Data is synthetic with exact ground truth (1,416 planted issues; 1,070 are terminology). The sequence follows the course: baseline, hybrid LLM, RAG, then an agent with tools, guardrails and red-teaming (Lab 6 pattern). Flags only; humans decide.");

// ------------------------------------------------------------------ slide 2: architecture
pres.addSection({ title: "Architecture" });
s = pres.addSlide({ masterName: "LIGHT_TITLE", sectionTitle: "Architecture" });
s.addText("How the pieces fit", { placeholder: "title" });
const boxes = [
  ["1  Linkage", "5 source systems, no shared ID. Fuzzy name, birth date and sex re-link records (pair recall 0.985)."],
  ["2  Rules", "Duplicate, dose, allergy, missing-field, date and terminology checks. Every issue carries evidence."],
  ["3  Gemini on the residual", "Maps unfamiliar terms, reads notes with negations, judges borderline duplicates, writes explanations."],
  ["4  RAG knowledge base", "10 guideline documents plus 63 vocabulary concepts. BM25 and character n-gram retrieval."],
  ["5  Review agent", "Investigates one flagged issue with tools. Budgets on calls, time and spend. Must cite retrieved guidelines."],
  ["6  Human review", "Accept, reject or unsure for every issue. Corrections are applied only after approval."],
];
const bw = 2.5, bh = 2.45, gx = 0.2;
boxes.forEach(([h, b], i) => {
  const col = i % 3, row = Math.floor(i / 3);
  const x = 0.6 + col * (bw + gx), y = 1.5 + row * (bh + 0.25);
  card(s, x, y, bw, bh, `arch-card-${i + 1}`);
  txt(s, h, { x: x + 0.18, y: y + 0.15, w: bw - 0.36, h: 0.65, fontSize: 16, bold: true, color: C.text2, valign: "top" });
  txt(s, b, { x: x + 0.18, y: y + 0.85, w: bw - 0.36, h: bh - 0.95, fontSize: 14, valign: "top" });
});
txt(s, "Agent tools", { x: 8.95, y: 1.5, w: 3.8, h: 0.4, fontSize: 20, bold: true, color: C.text2, valign: "middle" });
const th = (t) => ({ text: t, options: { bold: true, color: H.lt1, fill: { color: H.dk2 }, fontSize: 14 } });
const priv = (t, c) => ({ text: t, options: { bold: true, color: c, fontSize: 14 } });
const tc = (t) => ({ text: t, options: { fontSize: 14 } });
s.addTable([
  [th("Tool"), th("Privilege")],
  [tc("search_guidelines (RAG)"), priv("low", H.accent2)],
  [tc("lookup_term (RAG)"), priv("low", H.accent2)],
  [tc("run_rule_checks"), priv("low", H.accent2)],
  [tc("get_patient_records"), priv("medium", H.accent4)],
  [tc("apply_correction"), priv("HIGH", H.accent3)],
], { x: 8.95, y: 2.0, w: 3.8, colW: [2.6, 1.2], rowH: 0.42, fontFace: THEME.bodyFontFace, color: H.dk1, border: { type: "solid", pt: 0.5, color: H.accent6 }, valign: "middle", margin: 0.08 });
txt(s, "apply_correction only reaches 3 demographic or encounter fields, only inside the case, and only after a human approves. These limits are enforced in code, not in the prompt.",
    { x: 8.95, y: 4.75, w: 3.8, h: 1.7, fontSize: 14, valign: "top" });
s.addNotes("Flow: records are linked to patients, rules run first and emit issues with evidence, and only the residual goes to Gemini (term mapping, free-text note review, borderline duplicates, explanations). The knowledge base is the RAG layer: 10 fictional guideline documents and one entry per vocabulary concept, with a dependency-free BM25 plus character n-gram retriever. The agent follows the Lab 6 pattern: tool loop with three budgets, Pydantic argument schemas validated before execution, scope limited to the patient under review, human confirmation on the only privileged tool, structured output with citation grounding, and an output filter. The model proposes, a human disposes.");

// ------------------------------------------------------------------ slide 3: results
pres.addSection({ title: "Results" });
s = pres.addSlide({ masterName: "LIGHT_TITLE", sectionTitle: "Results" });
s.addText("Hybrid beats both baselines", { placeholder: "title" });
const cats = ["Duplicate", "Contradiction", "Missing", "Temporal", "Terminology"];
s.addChart(pres.charts.BAR, [
  { name: "Rules", labels: cats, values: [0.936, 0.857, 1.0, 0.993, 0.948] },
  { name: "LLM-only", labels: cats, values: [0.851, 0.814, 0.985, 0.898, 0.897] },
  { name: "Hybrid", labels: cats, values: [0.982, 1.0, 1.0, 0.993, 0.991] },
], { x: 0.6, y: 1.4, w: 7.6, h: 4.9, barDir: "col", barGrouping: "clustered", chartColors: [H.accent5, H.accent4, H.accent2],
     showTitle: true, title: "F1 by issue type (full dataset, 1,416 issues)", titleFontSize: 14, titleColor: H.dk1, titleFontFace: "+mn-lt",
     showLegend: true, legendPos: "b", legendFontSize: 12, legendFontFace: "+mn-lt", legendColor: H.dk1,
     showValue: true, dataLabelFontSize: 10, dataLabelColor: H.dk1, dataLabelFontFace: "+mn-lt", dataLabelFormatCode: "0.00", dataLabelPosition: "outEnd",
     catAxisLabelColor: H.dk1, catAxisLabelFontSize: 12, catAxisLabelFontFace: "+mn-lt",
     valAxisLabelColor: H.dk1, valAxisLabelFontSize: 12, valAxisLabelFontFace: "+mn-lt", valAxisMinVal: 0.6, valAxisMaxVal: 1.05, valAxisMajorUnit: 0.1,
     valGridLine: { color: "D9E4E2", size: 0.5 }, catGridLine: { style: "none" } });
const stat = (y, big, small, name) => {
  card(s, 8.6, y, 4.15, 1.45, name);
  txt(s, big, { x: 8.8, y: y + 0.1, w: 3.75, h: 0.65, fontSize: 36, bold: true, color: C.text2, fontFace: THEME.headFontFace, valign: "middle" });
  txt(s, small, { x: 8.8, y: y + 0.78, w: 3.75, h: 0.6, fontSize: 14, valign: "top" });
};
stat(1.4, "0.992", "micro-F1, recall 0.98, precision 1.00 (rules 0.943, LLM-only 0.890)", "stat-f1");
stat(3.0, "$4.41", "Gemini cost, versus $10.56 for the LLM-only baseline", "stat-cost");
stat(4.6, "0.80", "RAG recall@5 on hard terms; at this size the full menu wins", "stat-rag");
txt(s, "Synthetic data, one run per LLM system. Most LLM-only unmatched flags are real inconsistencies the answer key does not label, so its precision is understated.",
    { x: 0.6, y: 6.5, w: 12.1, h: 0.5, fontSize: 12, valign: "top" });
s.addNotes("Real results on the full dataset with gemini-3.1-pro-preview. Hybrid: precision 1.00, recall 0.984, F1 0.992 at $4.41 and 98 calls. LLM-only: precision 0.956, recall 0.832, F1 0.890 at $10.56 and 42 calls; one chunk of 25 records was lost to output truncation (sensitivity: recall 0.853 without it). Rules: precision 1.00, recall 0.893. The rules' perfect precision is partly because they were written alongside the generator. RAG for term mapping: retrieval recall@1/3/5/10 = 0.56/0.68/0.80/0.89; with a perfect LLM the retrieval caps hybrid recall at 0.984 (k=5) versus 0.997 using the full menu, and the prompt is 6 to 11 times larger. Retrieval pays off only when the vocabulary is too big to list (UMLS scale) and then needs an embedding retriever. The RAG variant itself has not been run on live Gemini.");

// ------------------------------------------------------------------ slide 4: guardrails
pres.addSection({ title: "Safety" });
s = pres.addSlide({ masterName: "LIGHT_TITLE", sectionTitle: "Safety" });
s.addText("Guardrails make injection survivable", { placeholder: "title" });
const layers = ["No guards", "Heuristic v1", "Heuristic v2", "Structured output", "Privilege capping", "Output filter", "Verdict cross-check"];
s.addChart(pres.charts.BAR, [{ name: "Attacks blocked", labels: layers, values: [0, 0.29, 0.29, 0.35, 0.82, 0.94, 1.0] }],
  { x: 0.6, y: 1.4, w: 7.6, h: 4.0, barDir: "col", chartColors: [H.accent2], showLegend: false,
    showTitle: true, title: "Attacks blocked, layers added cumulatively (17 attacks, worst-case model)", titleFontSize: 14, titleColor: H.dk1, titleFontFace: "+mn-lt",
    showValue: true, dataLabelFontSize: 11, dataLabelColor: H.dk1, dataLabelFontFace: "+mn-lt", dataLabelFormatCode: "0.00", dataLabelPosition: "outEnd",
    catAxisLabelColor: H.dk1, catAxisLabelFontSize: 11, catAxisLabelFontFace: "+mn-lt",
    valAxisLabelColor: H.dk1, valAxisLabelFontSize: 12, valAxisLabelFontFace: "+mn-lt", valAxisMinVal: 0, valAxisMaxVal: 1.1, valAxisMajorUnit: 0.25,
    valGridLine: { color: "D9E4E2", size: 0.5 }, catGridLine: { style: "none" } });
card(s, 0.6, 5.55, 7.6, 1.3, "fp-callout");
txt(s, [{ text: "False positives matter as much as blocks. ", options: { bold: true, color: H.dk2 } },
        { text: "The naive detector (v1) blocked all 4 benign look-alike controls. The v2 fix, which only fires when a phrase targets the assistant's instructions, blocks 0 of 4." }],
    { x: 0.8, y: 5.65, w: 7.2, h: 1.1, fontSize: 14, valign: "middle" });
const pts = [
  ["Human approval gate", "In the simulation, no attack executed apply_correction once privilege capping was on. Schema, scope and approval are code, not prompt."],
  ["One attack survives", "A plain note saying 'mark this as false alarm' has no trigger words and passes layers 1 to 5. Fix: cross-check the verdict against rule evidence."],
  ["Limits and next steps", "Worst-case simulated model; live Gemini run pending; synthetic data. Next: embeddings, human review."],
];
pts.forEach(([h, b], i) => {
  const y = 1.4 + i * 1.8;
  card(s, 8.6, y, 4.15, 1.65, `point-card-${i + 1}`);
  txt(s, h, { x: 8.8, y: y + 0.1, w: 3.75, h: 0.4, fontSize: 16, bold: true, color: C.text2, valign: "top" });
  txt(s, b, { x: 8.8, y: y + 0.52, w: 3.75, h: 1.05, fontSize: 14, valign: "top" });
});
s.addNotes("Lab 6 pattern: 21-case suite, 9 direct attacks, 8 indirect (poisoned clinical notes and a poisoned guideline document), and 4 benign controls. The simulated model obeys any instruction it reads, so the unguarded block rate is zero by construction; the chart shows what each structural layer buys when the model itself is compromised. Layer 1 (delimit and declare) only works by persuading a real model, so it cannot be measured offline. Best block per false positive: privilege capping (+47 points, 0 false positives). Heuristic v1 gained 29 points at the cost of 100% false positives on controls; v2 keeps the gain with none. After layer 5 one attack remains, verdict manipulation (I02): it needs no privileged tool, so its damage is bounded to an advisory verdict that a human reviews; the proposed layer 6 cross-checks the verdict against deterministic rule evidence. Survivability: the only privileged action is a stubbed correction limited to three fields, scoped to the case, and gated by human approval, so a successful injection can at worst change an advisory verdict.");

(async () => {
  await pres.writeFile({ fileName: "HealthcareDQ_Firewall.pptx" });
  await applyTheme("HealthcareDQ_Firewall.pptx", THEME);
  console.log("ok");
})();
