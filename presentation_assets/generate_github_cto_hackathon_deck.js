const pptxgen = require("pptxgenjs");

const pptx = new pptxgen();
pptx.layout = "LAYOUT_WIDE";
pptx.author = "DevFlow CTO";
pptx.company = "DevFlow CTO";
pptx.subject = "Hackathon leadership demo deck";
pptx.title = "DevFlow CTO: Agentic Issue-to-PR System";
pptx.lang = "en-US";
pptx.theme = { headFontFace: "Aptos Display", bodyFontFace: "Aptos", lang: "en-US" };
pptx.margin = 0;

const OUT = "DevFlow_CTO_Hackathon_Leadership_Deck.pptx";
const W = 13.333;
const H = 7.5;

const C = {
  bg: "F4F7FB",
  paper: "FFFFFF",
  ink: "102033",
  muted: "4E6179",
  line: "D6E0EC",
  navy: "17263A",
  navy2: "223650",
  teal: "16B8AE",
  tealDark: "078E89",
  mint: "E7F7F5",
  blue: "3E7BEF",
  blueSoft: "EAF1FF",
  green: "178C61",
  greenSoft: "EAF7F0",
  amber: "EC972D",
  amberSoft: "FFF3E2",
  purple: "6558F5",
  purpleSoft: "F0EEFF",
  red: "D95858",
  redSoft: "FCEDED",
  slateSoft: "EEF3F8",
};

function bg(slide, color = C.bg) {
  slide.addShape(pptx.ShapeType.rect, { x: 0, y: 0, w: W, h: H, fill: { color }, line: { color } });
}

function tx(slide, text, x, y, w, h, opts = {}) {
  slide.addText(text, {
    x,
    y,
    w,
    h,
    fontFace: opts.face || "Aptos",
    fontSize: opts.size || 10,
    color: opts.color || C.ink,
    bold: !!opts.bold,
    italic: !!opts.italic,
    align: opts.align || "left",
    valign: opts.valign || "top",
    margin: opts.margin === undefined ? 0.03 : opts.margin,
    fit: "shrink",
  });
}

function header(slide, title, subtitle, dark = false) {
  tx(slide, title, 0.42, 0.28, 9.4, 0.42, {
    face: "Aptos Display",
    size: 24,
    bold: true,
    color: dark ? "FFFFFF" : C.ink,
    margin: 0,
  });
  tx(slide, subtitle, 0.43, 0.78, 10.5, 0.28, {
    size: 10.8,
    color: dark ? "DDE9F8" : C.muted,
    margin: 0,
  });
}

function footer(slide, n, dark = false) {
  tx(slide, "DevFlow CTO | Hackathon demo", 0.42, 7.14, 2.7, 0.16, {
    size: 7.5,
    color: dark ? "C7D3E3" : "76879C",
    margin: 0,
  });
  tx(slide, String(n), 12.72, 7.14, 0.28, 0.16, {
    size: 7.5,
    color: dark ? "C7D3E3" : "76879C",
    align: "right",
    margin: 0,
  });
}

function box(slide, cfg) {
  const {
    x,
    y,
    w,
    h,
    title,
    body,
    fill = C.paper,
    line = C.line,
    accent,
    dark = false,
    titleSize = 10.4,
    bodySize = 8.2,
  } = cfg;
  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y,
    w,
    h,
    fill: { color: fill },
    line: { color: line, width: 0.8 },
  });
  if (accent) {
    slide.addShape(pptx.ShapeType.rect, { x, y, w: 0.08, h, fill: { color: accent }, line: { color: accent } });
  }
  tx(slide, title, x + 0.18, y + 0.14, w - 0.34, 0.23, {
    size: titleSize,
    bold: true,
    color: dark ? "FFFFFF" : C.ink,
    margin: 0,
  });
  if (body) {
    tx(slide, Array.isArray(body) ? body.join("\n") : body, x + 0.18, y + 0.48, w - 0.34, Math.max(0.2, h - 0.56), {
      size: bodySize,
      color: dark ? "EAF2FF" : C.muted,
      margin: 0,
    });
  }
}

function arrow(slide, x1, y1, x2, y2, opts = {}) {
  const x = Math.min(x1, x2);
  const y = Math.min(y1, y2);
  const w = Math.max(0.01, Math.abs(x2 - x1));
  const h = Math.max(0.01, Math.abs(y2 - y1));
  const l = { color: opts.color || C.navy, width: opts.width || 1.35 };
  if (opts.dash) l.dashType = "dash";
  if (opts.arrow !== false) {
    if (x2 >= x1 && y2 >= y1) l.endArrowType = "triangle";
    else l.beginArrowType = "triangle";
  }
  slide.addShape(pptx.ShapeType.line, { x, y, w, h, line: l });
}

function dot(slide, n, x, y, color) {
  slide.addShape(pptx.ShapeType.ellipse, { x, y, w: 0.34, h: 0.34, fill: { color }, line: { color } });
  tx(slide, String(n), x + 0.12, y + 0.095, 0.1, 0.1, { size: 7.4, bold: true, color: "FFFFFF", align: "center", margin: 0 });
}

function slide1() {
  const s = pptx.addSlide();
  bg(s, C.navy);
  tx(s, "DevFlow CTO", 0.62, 0.68, 4.2, 0.52, { face: "Aptos Display", size: 31, bold: true, color: "FFFFFF", margin: 0 });
  tx(s, "Agentic Issue-to-PR System", 0.64, 1.28, 6.4, 0.38, { size: 17, bold: true, color: C.teal, margin: 0 });
  tx(s, "A repo-aware AI workflow that turns GitHub issues into scoped, validated, human-approved pull requests.", 0.66, 1.86, 7.4, 0.55, { size: 13, color: "DDE9F8", margin: 0 });
  const xs = [0.68, 3.0, 5.32, 7.64, 9.96];
  const cards = [
    ["Intake", "GitHub issues\nbranches\ncomments"],
    ["Understand", "repo index\nsymbols\nruntime logs"],
    ["Implement", "Aider in isolated\nworkspace"],
    ["Validate", "parsers\nreviewer agent\nretry loop"],
    ["Approve", "editable proposal\nGitHub PR"],
  ];
  for (let i = 0; i < cards.length; i++) {
    box(s, { x: xs[i], y: 3.2, w: 1.84, h: 1.22, title: cards[i][0], body: cards[i][1], fill: i === 2 ? C.teal : C.navy2, line: i === 2 ? C.teal : "41536B", dark: true, titleSize: 11.5, bodySize: 8.4 });
    if (i < cards.length - 1) arrow(s, xs[i] + 1.84, 3.82, xs[i + 1], 3.82, { color: "DDE9F8", width: 1.4 });
  }
  box(s, { x: 0.68, y: 5.18, w: 6.85, h: 0.54, title: "Leadership lens", body: "Less engineering drag, better review quality, safer AI adoption.", fill: "17394A", line: C.teal, dark: true, titleSize: 9, bodySize: 8 });
  tx(s, "Demo promise: show a normal issue becoming a reviewable PR without AI directly writing to GitHub.", 0.72, 5.98, 8.8, 0.3, { size: 11.5, color: "FFFFFF", margin: 0 });
  footer(s, 1, true);
}

function slide2() {
  const s = pptx.addSlide();
  bg(s);
  header(s, "DevFlow CTO Application Architecture", "Layered flow from work-item intake to governed PR creation");

  const cols = [
    { x: 0.38, w: 2.35, title: "1. Experience Layer", fill: "F8FBFF" },
    { x: 2.98, w: 2.35, title: "2. Flask Orchestration", fill: "F8FFFD" },
    { x: 5.58, w: 2.35, title: "3. Repository Intelligence", fill: "FAFFFB" },
    { x: 8.18, w: 2.35, title: "4. Agent Runtime", fill: "FFF9F0" },
    { x: 10.78, w: 2.15, title: "5. Governance + Output", fill: "F9FAFE" },
  ];
  cols.forEach((col) => {
    s.addShape(pptx.ShapeType.roundRect, { x: col.x, y: 1.2, w: col.w, h: 5.78, fill: { color: col.fill }, line: { color: C.line, width: 0.9 } });
    tx(s, col.title, col.x + 0.18, 1.44, col.w - 0.28, 0.22, { size: 10.6, bold: true, margin: 0 });
  });

  box(s, { x: 0.58, y: 1.9, w: 1.95, h: 0.76, title: "GitHub Issues", body: "bug/enhancement\ncomments + priority", fill: C.blueSoft, accent: C.blue, titleSize: 9.2, bodySize: 7.8 });
  box(s, { x: 0.58, y: 2.95, w: 1.95, h: 0.76, title: "Branch Controls", body: "read branch\nPR target branch", fill: C.paper, accent: C.teal, titleSize: 9.2, bodySize: 7.8 });
  box(s, { x: 0.58, y: 4.0, w: 1.95, h: 0.76, title: "Review Screens", body: "Aider status\nproposal diff\neditable files", fill: C.paper, accent: C.green, titleSize: 9.2, bodySize: 7.8 });

  box(s, { x: 3.18, y: 1.9, w: 1.95, h: 0.76, title: "Flask Routes", body: "/issues\n/aider-run\n/proposals", fill: C.mint, accent: C.teal, titleSize: 9.2, bodySize: 7.8 });
  box(s, { x: 3.18, y: 2.95, w: 1.95, h: 0.76, title: "Job Registry", body: "async jobs\npolling JSON\nvisible logs", fill: C.paper, accent: C.blue, titleSize: 9.2, bodySize: 7.8 });
  box(s, { x: 3.18, y: 4.0, w: 1.95, h: 0.76, title: "Proposal Store", body: "diff snapshot\nsummary/test plan\napproval state", fill: C.paper, accent: C.green, titleSize: 9.2, bodySize: 7.8 });

  box(s, { x: 5.78, y: 1.9, w: 1.95, h: 0.76, title: "Repo Index", body: "file chunks\nlanguage + size\nbranch context", fill: C.greenSoft, accent: C.green, titleSize: 9.2, bodySize: 7.8 });
  box(s, { x: 5.78, y: 2.95, w: 1.95, h: 0.76, title: "Code Signals", body: "routes, imports\nforms, ids\nstate ownership", fill: C.paper, accent: C.purple, titleSize: 9.2, bodySize: 7.8 });
  box(s, { x: 5.78, y: 4.0, w: 1.95, h: 0.76, title: "Agent Memory", body: "lessons from rejects\nrepo observations\nretry guidance", fill: C.paper, accent: C.amber, titleSize: 9.2, bodySize: 7.8 });

  box(s, { x: 8.38, y: 1.9, w: 1.95, h: 0.76, title: "Planning Agent", body: "scope\nselected files\ncontext pack", fill: C.purpleSoft, accent: C.purple, titleSize: 9.2, bodySize: 7.8 });
  box(s, { x: 8.38, y: 2.95, w: 1.95, h: 0.76, title: "Aider CLI", body: "isolated clone\nlimited files\ngit diff", fill: C.amberSoft, accent: C.amber, titleSize: 9.2, bodySize: 7.8 });
  box(s, { x: 8.38, y: 4.0, w: 1.95, h: 0.76, title: "Reviewer Agent", body: "issue alignment\nmissed files\nlogic review", fill: C.paper, accent: C.red, titleSize: 9.2, bodySize: 7.8 });

  box(s, { x: 10.98, y: 1.9, w: 1.65, h: 0.76, title: "Validators", body: "AST/Jinja/JSON\nunsafe patterns", fill: C.redSoft, accent: C.red, titleSize: 9.0, bodySize: 7.5 });
  box(s, { x: 10.98, y: 2.95, w: 1.65, h: 0.76, title: "Human Gate", body: "diff review\nedit final code", fill: C.blueSoft, accent: C.blue, titleSize: 9.0, bodySize: 7.5 });
  box(s, { x: 10.98, y: 4.0, w: 1.65, h: 0.76, title: "GitHub PR", body: "new branch\nchosen base\nno auto-merge", fill: C.slateSoft, accent: C.navy, titleSize: 9.0, bodySize: 7.5 });

  arrow(s, 2.53, 2.28, 3.18, 2.28, { color: C.navy, width: 1.3 });
  arrow(s, 5.13, 2.28, 5.78, 2.28, { color: C.navy, width: 1.3 });
  arrow(s, 7.73, 2.28, 8.38, 2.28, { color: C.navy, width: 1.3 });
  arrow(s, 10.33, 2.28, 10.98, 2.28, { color: C.navy, width: 1.3 });
  arrow(s, 7.73, 3.33, 8.38, 3.33, { color: C.amber, width: 1.25 });
  arrow(s, 11.8, 2.66, 11.8, 2.95, { color: C.navy, width: 1.05 });
  arrow(s, 11.8, 3.71, 11.8, 4.0, { color: C.navy, width: 1.05 });
  arrow(s, 10.33, 4.38, 10.98, 3.33, { color: C.red, width: 1.0 });
  arrow(s, 10.33, 4.88, 8.38, 4.88, { color: C.red, dash: true, width: 1.0 });
  arrow(s, 7.73, 5.08, 8.38, 1.9, { color: C.amber, dash: true, width: 1.0 });
  tx(s, "retry feedback", 8.72, 5.02, 1.4, 0.16, { size: 7.5, color: C.red, margin: 0 });
  tx(s, "memory enriches future plans", 6.3, 5.22, 2.45, 0.16, { size: 7.5, color: C.amber, margin: 0 });
  box(s, { x: 0.58, y: 5.42, w: 12.05, h: 0.62, title: "Core control principle", body: "AI can discover, plan, edit, and review. GitHub only changes after validators pass and a human approves the proposal.", fill: C.navy, line: C.navy, dark: true, titleSize: 9.2, bodySize: 8.0 });
  footer(s, 2);
}

function slide3() {
  const s = pptx.addSlide();
  bg(s, "F6F8FC");
  header(s, "What Each Component Does", "Clear ownership makes the system explainable to judges, engineers, and leaders");
  const rows = [
    ["Flask UI + API", "Runs the dashboard, issue detail, Aider job page, and proposal review screen.", "Keeps the experience familiar: issue -> diff -> approve PR."],
    ["Repo Index", "Caches file chunks, metadata, route/template/import signals, and branch-specific context.", "Lets AI work with large repos without dumping every file into the prompt."],
    ["Planning Agent", "Reads the issue, selected files, logs, git state, and memory before Aider edits.", "Improves file selection and gives Aider a grounded implementation plan."],
    ["Aider Backend", "Clones the read branch, edits only selected context, and returns a captured git diff.", "Keeps AI code generation isolated and reviewable."],
    ["Validators + Reviewer", "Parse code/templates and ask a second agent if the patch actually solves the issue.", "Blocks broken or irrelevant changes and creates retry guidance."],
    ["Proposal + PR Layer", "Shows summary, test plan, diffs, logs, warnings, and final editable file contents.", "Human approval remains the only path to GitHub PR creation."],
  ];
  const x = [0.55, 3.0, 7.25];
  tx(s, "Component", x[0], 1.22, 1.8, 0.18, { size: 9.8, bold: true, color: C.muted, margin: 0 });
  tx(s, "Role in the application", x[1], 1.22, 3.1, 0.18, { size: 9.8, bold: true, color: C.muted, margin: 0 });
  tx(s, "Why it matters", x[2], 1.22, 3.1, 0.18, { size: 9.8, bold: true, color: C.muted, margin: 0 });
  for (let i = 0; i < rows.length; i++) {
    const y = 1.58 + i * 0.84;
    s.addShape(pptx.ShapeType.roundRect, { x: 0.42, y, w: 12.48, h: 0.67, fill: { color: i % 2 ? "FFFFFF" : "F9FBFE" }, line: { color: C.line, width: 0.5 } });
    tx(s, rows[i][0], x[0], y + 0.17, 2.05, 0.16, { size: 9.3, bold: true, color: [C.blue, C.green, C.purple, C.amber, C.red, C.tealDark][i], margin: 0 });
    tx(s, rows[i][1], x[1], y + 0.13, 3.55, 0.26, { size: 8.4, color: C.ink, margin: 0 });
    tx(s, rows[i][2], x[2], y + 0.13, 4.6, 0.26, { size: 8.4, color: C.muted, margin: 0 });
  }
  footer(s, 3);
}

function slide4() {
  const s = pptx.addSlide();
  bg(s);
  header(s, "Agent Loop: How the System Behaves Like a Careful Engineer", "Observe, plan, edit, validate, review, retry, and remember");
  const loop = [
    ["Observe", "issue + comments\nlogs + git state", C.blue, C.blueSoft],
    ["Plan", "scope, affected files\nimplementation approach", C.purple, C.purpleSoft],
    ["Edit", "Aider CLI\nisolated workspace", C.amber, C.amberSoft],
    ["Validate", "syntax/template checks\nunsafe-pattern checks", C.tealDark, C.mint],
    ["Review", "does patch solve issue?\nmissed dependency?", C.red, C.redSoft],
    ["Remember", "store lessons\nimprove next run", C.green, C.greenSoft],
  ];
  const pts = [[0.5, 2.05], [2.62, 2.05], [4.74, 2.05], [6.86, 2.05], [8.98, 2.05], [11.1, 2.05]];
  for (let i = 0; i < loop.length; i++) {
    const [t, b, c, f] = loop[i];
    box(s, { x: pts[i][0], y: pts[i][1], w: 1.62, h: 1.0, title: t, body: b, fill: f, accent: c, titleSize: 10.3, bodySize: 8.0 });
    if (i < loop.length - 1) arrow(s, pts[i][0] + 1.62, pts[i][1] + 0.5, pts[i + 1][0], pts[i + 1][1] + 0.5, { color: C.navy, width: 1.15 });
  }
  arrow(s, 9.75, 3.28, 5.55, 3.28, { color: C.red, dash: true, width: 1.05 });
  tx(s, "retry feedback to Aider", 6.55, 3.42, 1.8, 0.18, { size: 8.1, color: C.red, margin: 0 });
  arrow(s, 11.9, 3.72, 3.2, 3.72, { color: C.green, dash: true, width: 1.05 });
  tx(s, "memory enriches next planning cycle", 5.05, 3.88, 2.8, 0.18, { size: 8.1, color: C.green, margin: 0 });
  box(s, { x: 0.7, y: 4.72, w: 3.7, h: 1.0, title: "Pass condition", body: "Validators pass, reviewer accepts issue alignment, and the proposal is understandable to a human reviewer.", fill: C.greenSoft, accent: C.green, titleSize: 10.8, bodySize: 8.3 });
  box(s, { x: 4.82, y: 4.72, w: 3.7, h: 1.0, title: "Retry condition", body: "If the patch is wrong, feedback returns to Aider with exact reasons and affected files.", fill: C.redSoft, accent: C.red, titleSize: 10.8, bodySize: 8.3 });
  box(s, { x: 8.94, y: 4.72, w: 3.7, h: 1.0, title: "Human control", body: "Generated code remains a proposal. GitHub changes only after review and approval.", fill: C.blueSoft, accent: C.blue, titleSize: 10.8, bodySize: 8.3 });
  footer(s, 4);
}

function slide5() {
  const s = pptx.addSlide();
  bg(s, "F6F8FC");
  header(s, "Demo Story for Judges", "A simple, credible path through the product");
  const steps = [
    ["1. Start with a real GitHub issue", "Use normal tester language, not a prompt engineered for the AI."],
    ["2. Show context selection", "Explain why the app chose files: routes, templates, imports, styles, and repo index evidence."],
    ["3. Run the agent", "Aider edits an isolated clone while the job page shows concise status and reviewer logs."],
    ["4. Review the proposal", "Open the diff, validation warnings, run timeline, summary, and test plan."],
    ["5. Approve only if sane", "The PR button is a control point, not a formality. The human still owns the merge path."],
  ];
  for (let i = 0; i < steps.length; i++) {
    const y = 1.35 + i * 0.88;
    dot(s, i + 1, 0.65, y + 0.08, [C.blue, C.teal, C.amber, C.purple, C.green][i]);
    box(s, { x: 1.12, y, w: 11.2, h: 0.61, title: steps[i][0], body: steps[i][1], fill: C.paper, accent: [C.blue, C.teal, C.amber, C.purple, C.green][i], titleSize: 9.8, bodySize: 8.3 });
  }
  box(s, { x: 1.12, y: 5.98, w: 11.2, h: 0.8, title: "Best demo close", body: "This is not an auto-coding toy. It is a controlled engineering workflow that makes AI useful inside existing GitHub habits.", fill: C.navy, line: C.navy, dark: true, titleSize: 10.2, bodySize: 8.4 });
  footer(s, 5);
}

slide1();
slide2();
slide3();
slide4();
slide5();

pptx.writeFile({ fileName: OUT });
