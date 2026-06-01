const pptxgen = require("pptxgenjs");

const pptx = new pptxgen();
pptx.layout = "LAYOUT_WIDE";
pptx.author = "GitHub CTO";
pptx.subject = "Agentic SDLC demo";
pptx.title = "GitHub CTO Demo";
pptx.company = "GitHub CTO";
pptx.lang = "en-US";
pptx.theme = {
  headFontFace: "Aptos Display",
  bodyFontFace: "Aptos",
  lang: "en-US",
};
pptx.margin = 0;

const W = 13.333;
const H = 7.5;

const C = {
  bg: "F4F7FB",
  paper: "FFFFFF",
  ink: "102033",
  muted: "50627A",
  line: "D5DEE9",
  navy: "203149",
  dark: "142235",
  teal: "18B7AD",
  tealDark: "07948D",
  mint: "E8F6F4",
  blue: "3E7BEF",
  blueSoft: "EAF1FF",
  amber: "E9952F",
  amberSoft: "FFF4E4",
  green: "16845D",
  greenSoft: "E9F6EF",
  red: "D95D5D",
  redSoft: "FCEEEE",
  purple: "6C63FF",
  purpleSoft: "F0EFFF",
};

const S = {
  title: { fontFace: "Aptos Display", color: C.ink, bold: true, margin: 0, breakLine: false },
  body: { fontFace: "Aptos", color: C.muted, margin: 0.04, breakLine: false, fit: "shrink" },
};

function bg(slide, color = C.bg) {
  slide.addShape(pptx.ShapeType.rect, {
    x: 0,
    y: 0,
    w: W,
    h: H,
    fill: { color },
    line: { color },
  });
}

function text(slide, value, x, y, w, h, opts = {}) {
  slide.addText(value, {
    x,
    y,
    w,
    h,
    fontFace: opts.fontFace || "Aptos",
    fontSize: opts.fontSize || 10,
    bold: !!opts.bold,
    italic: !!opts.italic,
    color: opts.color || C.ink,
    align: opts.align || "left",
    valign: opts.valign || "top",
    margin: opts.margin === undefined ? 0.03 : opts.margin,
    fit: opts.fit || "shrink",
    breakLine: false,
  });
}

function label(slide, value, x, y, w, color = C.ink) {
  text(slide, value, x, y, w, 0.23, { fontSize: 10, bold: true, color, margin: 0 });
}

function title(slide, main, sub) {
  text(slide, main, 0.2, 0.18, 8.6, 0.42, {
    fontFace: "Aptos Display",
    fontSize: 24,
    bold: true,
    color: C.ink,
    margin: 0,
  });
  if (sub) {
    text(slide, sub, 0.2, 0.68, 9.8, 0.24, {
      fontSize: 10.5,
      color: C.muted,
      margin: 0,
    });
  }
}

function pill(slide, value, x, y, w, opts = {}) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y,
    w,
    h: opts.h || 0.34,
    fill: { color: opts.fill || "EDF3FA" },
    line: { color: opts.line || C.line, width: 0.8 },
  });
  text(slide, value, x + 0.12, y + 0.09, w - 0.24, 0.16, {
    fontSize: opts.fontSize || 7.4,
    bold: !!opts.bold,
    color: opts.color || C.muted,
    align: opts.align || "center",
    margin: 0,
  });
}

function box(slide, cfg) {
  const {
    x,
    y,
    w,
    h,
    head,
    body,
    fill = C.paper,
    line = C.line,
    headColor = C.ink,
    bodyColor = C.muted,
    dark = false,
    accent,
    radius = true,
    fsHead = 10.5,
    fsBody = 7.2,
  } = cfg;
  const shapeOpts = {
    x,
    y,
    w,
    h,
    fill: { color: fill },
    line: { color: line, width: 0.8 },
  };
  if (cfg.shadow) {
    shapeOpts.shadow = { type: "outer", color: "000000", opacity: 0.09, blur: 4, offset: 1, angle: 45 };
  }
  slide.addShape(radius ? pptx.ShapeType.roundRect : pptx.ShapeType.rect, shapeOpts);
  if (accent) {
    slide.addShape(pptx.ShapeType.rect, {
      x,
      y,
      w: 0.06,
      h,
      fill: { color: accent },
      line: { color: accent },
    });
  }
  text(slide, head, x + 0.16, y + 0.15, w - 0.28, 0.22, {
    fontSize: fsHead,
    bold: true,
    color: dark ? "FFFFFF" : headColor,
    margin: 0,
  });
  const bodyLines = Array.isArray(body) ? body.join("\n") : body;
  if (bodyLines) {
    text(slide, bodyLines, x + 0.16, y + 0.44, w - 0.3, Math.max(0.18, h - 0.52), {
      fontSize: fsBody,
      color: dark ? "E9F1FF" : bodyColor,
      margin: 0,
      fit: "shrink",
    });
  }
}

function section(slide, n, name, x, y, w) {
  text(slide, `${n}. ${name}`, x, y, w, 0.22, {
    fontSize: 10.4,
    bold: true,
    color: C.ink,
    margin: 0,
  });
}

function panel(slide, x, y, w, h, fill = "F8FAFD") {
  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y,
    w,
    h,
    fill: { color: fill },
    line: { color: C.line, width: 0.7 },
  });
}

function arrow(slide, x1, y1, x2, y2, opts = {}) {
  const startX = Math.min(x1, x2);
  const startY = Math.min(y1, y2);
  const width = Math.max(0.01, Math.abs(x2 - x1));
  const height = Math.max(0.01, Math.abs(y2 - y1));
  const line = {
    color: opts.color || C.navy,
    width: opts.width || 1.6,
  };
  if (opts.begin || x2 < x1 || y2 < y1) line.beginArrowType = "triangle";
  if (opts.end !== false && x2 >= x1 && y2 >= y1) line.endArrowType = "triangle";
  if (opts.dash) line.dashType = "dash";
  slide.addShape(pptx.ShapeType.line, {
    x: startX,
    y: startY,
    w: width,
    h: height,
    line,
  });
}

function dot(slide, x, y, color = C.teal) {
  slide.addShape(pptx.ShapeType.ellipse, {
    x,
    y,
    w: 0.12,
    h: 0.12,
    fill: { color },
    line: { color },
  });
}

function miniCard(slide, x, y, w, h, head, body, fill, accent) {
  box(slide, {
    x,
    y,
    w,
    h,
    head,
    body,
    fill,
    accent,
    fsHead: 9.8,
    fsBody: 6.9,
  });
}

function footer(slide, page) {
  text(slide, "GitHub CTO demo", 0.28, 7.17, 2.2, 0.15, {
    fontSize: 6.8,
    color: "75859A",
    margin: 0,
  });
  text(slide, String(page), 12.72, 7.17, 0.28, 0.15, {
    fontSize: 6.8,
    color: "75859A",
    margin: 0,
    align: "right",
  });
}

function slide1() {
  const slide = pptx.addSlide();
  bg(slide);
  title(
    slide,
    "Agentic GitHub CTO War Room",
    "GitHub issues become scoped, validated, human-approved pull requests through repo-aware agent orchestration"
  );
  pill(slide, "Future connectors: Jira · ADO · CI/CD · Observability · Security Scanners", 9.5, 0.18, 3.25, {
    h: 0.32,
    fill: "EEF3FA",
    fontSize: 6.7,
  });

  section(slide, 1, "Inputs", 0.5, 1.05, 2.5);
  const topY = 1.43;
  const topH = 0.86;
  miniCard(slide, 0.5, topY, 1.78, topH, "GitHub Issue", ["Bug or enhancement", "Acceptance intent"], C.blueSoft, C.blue);
  miniCard(slide, 2.5, topY, 1.78, topH, "Repo + Branch", ["Read branch", "PR target branch"], C.greenSoft, C.green);
  miniCard(slide, 4.5, topY, 1.78, topH, "Runtime Signals", ["Logs, git state", "Prior failures"], C.amberSoft, C.amber);
  box(slide, {
    x: 6.5,
    y: topY,
    w: 1.95,
    h: topH,
    head: "Frontend UI",
    body: ["Select files", "Review diffs", "Approve PR only"],
    fill: C.navy,
    line: C.navy,
    dark: true,
    fsHead: 10,
    fsBody: 6.8,
  });
  box(slide, {
    x: 9.05,
    y: topY,
    w: 2.1,
    h: topH,
    head: "Flask API Gateway",
    body: ["/issues", "/aider-run", "/proposals"],
    fill: C.teal,
    line: C.teal,
    dark: true,
    fsHead: 10,
    fsBody: 6.8,
  });
  arrow(slide, 2.28, 1.86, 2.5, 1.86);
  arrow(slide, 4.28, 1.86, 4.5, 1.86);
  arrow(slide, 6.28, 1.86, 6.5, 1.86);
  arrow(slide, 8.45, 1.86, 9.05, 1.86, { color: C.tealDark, width: 1.7 });

  section(slide, 2, "Repository Intelligence Layer", 0.5, 2.72, 3.3);
  panel(slide, 0.5, 3.02, 11.3, 1.22, "F9FBFE");
  const midY = 3.22;
  const midH = 0.62;
  const mid = [
    ["Repo Indexer", "Scan once, cache chunks"],
    ["Metadata", "Path, kind, size, role"],
    ["Symbols", "Routes, functions, templates"],
    ["Imports", "Dependencies + callers"],
    ["Retriever", "Rank useful snippets"],
    ["Expansion", "Related files + owners"],
  ];
  let x = 0.78;
  for (const [h, b] of mid) {
    box(slide, {
      x,
      y: midY,
      w: 1.55,
      h: midH,
      head: h,
      body: b,
      fill: C.paper,
      fsHead: 8.6,
      fsBody: 5.9,
    });
    if (x < 8.95) arrow(slide, x + 1.55, midY + 0.31, x + 1.78, midY + 0.31, { width: 1.3 });
    x += 1.78;
  }
  box(slide, {
    x: 12.03,
    y: 3.12,
    w: 0.9,
    h: 0.98,
    head: "CACHE",
    body: [".repo_index", "lessons", "signals"],
    fill: C.dark,
    line: C.dark,
    dark: true,
    fsHead: 7.6,
    fsBody: 5.8,
  });
  arrow(slide, 11.15, 3.53, 12.03, 3.53, { width: 1.4 });
  arrow(slide, 12.03, 4.0, 2.28, 4.0, { dash: true, color: C.navy, width: 1.1, end: false });
  arrow(slide, 2.28, 4.0, 2.28, 3.02, { dash: true, color: C.navy, width: 1.1 });

  section(slide, 3, "Token-Bounded Context + Agent Orchestration", 0.5, 4.62, 4.3);
  box(slide, {
    x: 0.5,
    y: 4.95,
    w: 2.55,
    h: 0.95,
    head: "Context Pack",
    body: ["Issue + comments", "selected code + evidence", "logs + git state"],
    fill: C.mint,
    line: "B9E6DF",
    fsHead: 9.2,
    fsBody: 6.4,
  });
  panel(slide, 3.5, 4.77, 4.25, 1.35, "F7FAFF");
  label(slide, "Agent Pipeline", 3.78, 4.95, 1.3);
  const smalls = [
    ["Planner", 3.78, 5.2],
    ["Codebase Mapper", 5.05, 5.2],
    ["Aider Editor", 6.32, 5.2],
    ["Validators", 3.78, 5.58],
    ["Reviewer Gate", 5.05, 5.58],
    ["Memory Writer", 6.32, 5.58],
  ];
  for (const [s, sx, sy] of smalls) {
    pill(slide, s, sx, sy, 1.08, { h: 0.27, fontSize: 5.8, fill: C.paper });
  }
  box(slide, {
    x: 8.2,
    y: 4.95,
    w: 1.75,
    h: 0.95,
    head: "Runtime Mode",
    body: ["Isolated clone", "limited files", "no PR write"],
    fill: C.blue,
    line: C.blue,
    dark: true,
    fsHead: 8.8,
    fsBody: 6.1,
  });
  box(slide, {
    x: 10.45,
    y: 4.95,
    w: 1.7,
    h: 0.95,
    head: "LLM Backend",
    body: ["OpenAI model", "Aider CLI", "review agent"],
    fill: C.amber,
    line: C.amber,
    dark: true,
    fsHead: 8.8,
    fsBody: 6.1,
  });
  arrow(slide, 3.05, 5.42, 3.5, 5.42, { color: C.tealDark });
  arrow(slide, 7.75, 5.42, 8.2, 5.42);
  arrow(slide, 9.95, 5.42, 10.45, 5.42);
  arrow(slide, 6.88, 5.83, 6.88, 6.55, { dash: true, color: C.red, width: 1.1, end: false });
  arrow(slide, 6.88, 6.55, 4.05, 6.55, { dash: true, color: C.red, width: 1.1 });
  text(slide, "Reviewer fail → retry with targeted feedback", 4.1, 6.36, 2.8, 0.16, {
    fontSize: 6.1,
    color: C.red,
    margin: 0,
  });

  section(slide, 4, "Output", 0.5, 6.3, 1.5);
  box(slide, {
    x: 0.5,
    y: 6.48,
    w: 2.2,
    h: 0.58,
    head: "Review Proposal",
    body: "diff + narrative + logs",
    fill: C.paper,
    accent: C.teal,
    fsHead: 7.8,
    fsBody: 5.3,
  });
  box(slide, {
    x: 3.05,
    y: 6.48,
    w: 2.2,
    h: 0.58,
    head: "Human Approval",
    body: "edit final content",
    fill: C.paper,
    accent: C.green,
    fsHead: 7.8,
    fsBody: 5.3,
  });
  box(slide, {
    x: 5.6,
    y: 6.48,
    w: 2.2,
    h: 0.58,
    head: "GitHub PR",
    body: "target branch only",
    fill: C.paper,
    accent: C.blue,
    fsHead: 7.8,
    fsBody: 5.3,
  });
  arrow(slide, 2.7, 6.77, 3.05, 6.77);
  arrow(slide, 5.25, 6.77, 5.6, 6.77);
  arrow(slide, 10.45, 5.9, 6.7, 6.48, { color: C.tealDark, width: 1.2 });

  footer(slide, 1);
}

function slide2() {
  const slide = pptx.addSlide();
  bg(slide, "F6F8FC");
  title(slide, "Demo Journey: From Issue to Reviewable PR", "A practical flow the evaluator can watch end-to-end during the demo");

  const steps = [
    ["1", "Create Issue", "A tester files a normal GitHub issue with expected behavior, not a developer prompt.", C.blue],
    ["2", "Rank Context", "The app classifies scope and selects likely files using index evidence, symbols, routes, imports, and metadata.", C.tealDark],
    ["3", "Agent Edits", "Aider works in an isolated clone on selected files and receives project-specific instructions.", C.amber],
    ["4", "Quality Gate", "Deterministic validators and a reviewer agent inspect the patch against the issue.", C.purple],
    ["5", "Human Review", "The user sees a diff, summary, test plan, run timeline, and can edit final file contents.", C.green],
    ["6", "Create PR", "Only after approval does the app create a branch and PR against the selected target branch.", C.navy],
  ];

  let x = 0.55;
  for (let i = 0; i < steps.length; i++) {
    const [num, head, body, color] = steps[i];
    slide.addShape(pptx.ShapeType.ellipse, {
      x,
      y: 1.42,
      w: 0.44,
      h: 0.44,
      fill: { color },
      line: { color },
    });
    text(slide, num, x + 0.15, 1.54, 0.14, 0.12, { fontSize: 8.5, bold: true, color: "FFFFFF", margin: 0, align: "center" });
    box(slide, {
      x,
      y: 2.02,
      w: 1.8,
      h: 1.22,
      head,
      body,
      fill: C.paper,
      accent: color,
      fsHead: 9.5,
      fsBody: 6.5,
    });
    if (i < steps.length - 1) arrow(slide, x + 1.85, 2.63, x + 2.13, 2.63, { color: color, width: 1.3 });
    x += 2.08;
  }

  panel(slide, 0.55, 4.0, 12.1, 1.42, "FFFFFF");
  text(slide, "What makes the demo credible", 0.82, 4.22, 2.5, 0.22, { fontSize: 12, bold: true, margin: 0 });
  const claims = [
    ["Real workflow", "GitHub issues, branches, diffs, and PRs; not a chatbot mockup."],
    ["Human-controlled", "The system proposes. The user reviews, edits, and approves."],
    ["Evidence-led", "Selected files are backed by repo index, code signals, and runtime context."],
    ["Recoverable", "Bad generations are rejected, logged, and converted into retry guidance."],
  ];
  for (let i = 0; i < claims.length; i++) {
    const cx = 0.82 + i * 2.95;
    dot(slide, cx, 4.68, [C.teal, C.green, C.blue, C.amber][i]);
    text(slide, claims[i][0], cx + 0.18, 4.64, 1.45, 0.16, { fontSize: 8.4, bold: true, margin: 0 });
    text(slide, claims[i][1], cx + 0.18, 4.88, 2.35, 0.34, { fontSize: 6.7, color: C.muted, margin: 0 });
  }

  box(slide, {
    x: 0.55,
    y: 5.95,
    w: 12.1,
    h: 0.68,
    head: "Demo success signal",
    body: "The audience sees the app reason over an issue, select context, produce a reviewable patch, explain the run, and keep GitHub untouched until approval.",
    fill: C.dark,
    line: C.dark,
    dark: true,
    fsHead: 9,
    fsBody: 6.8,
  });
  footer(slide, 2);
}

function slide3() {
  const slide = pptx.addSlide();
  bg(slide, "F4F7FB");
  title(slide, "Where AI Actually Adds Leverage", "The product is valuable because AI changes the cost and quality curve of small engineering work");

  const cards = [
    ["Context Discovery", "Finds the files a human would search for manually.\nSignals: routes, templates, imports, styles, config, tests.\nOutput: smaller context pack, fewer missed dependencies.", C.blueSoft, C.blue],
    ["Root-Cause Planning", "Turns a vague issue into an implementation hypothesis.\nUses selected files, logs, git state, and prior failures.\nOutput: an edit plan before Aider starts changing code.", C.mint, C.teal],
    ["Targeted Code Drafting", "Aider edits in an isolated clone with strict file context.\nThe app captures normal git diff output.\nOutput: reviewable changes instead of opaque generated text.", C.amberSoft, C.amber],
    ["Semantic Review", "A second agent compares issue intent against the patch.\nIt looks for missed routes, nested forms, state conflicts, and UI gaps.\nOutput: reject, retry, or approve-for-review.", C.purpleSoft, C.purple],
    ["Learning Loop", "Failures become memory: what was missed and why.\nFuture runs receive lessons plus repo observations.\nOutput: fewer repeated mistakes across similar issues.", C.greenSoft, C.green],
    ["Approval Experience", "The user sees diff, summary, test plan, warnings, and run trace.\nFinal file content remains editable.\nOutput: GitHub PR only after deliberate approval.", "F8F9FC", C.navy],
  ];

  for (let i = 0; i < cards.length; i++) {
    const col = i % 3;
    const row = Math.floor(i / 3);
    miniCard(slide, 0.65 + col * 4.1, 1.4 + row * 1.85, 3.45, 1.35, cards[i][0], cards[i][1], cards[i][2], cards[i][3]);
  }

  panel(slide, 0.65, 5.45, 12.0, 0.92, "FFFFFF");
  text(slide, "Net effect", 0.9, 5.72, 1.3, 0.18, { fontSize: 10.2, bold: true, margin: 0 });
  text(
    slide,
    "Engineers spend less time finding context and writing first-pass fixes, while reviewers retain control over quality and release risk.",
    2.1,
    5.69,
    9.85,
    0.22,
    { fontSize: 8.6, color: C.ink, margin: 0 }
  );
  footer(slide, 3);
}

function slide4() {
  const slide = pptx.addSlide();
  bg(slide, "F6F8FC");
  title(slide, "Safety Model: Fast Suggestions, Slow Approval", "The architecture is designed so AI can move quickly without directly changing production code");

  panel(slide, 0.55, 1.25, 12.2, 4.35, "FFFFFF");
  const left = [
    ["Isolated Workspace", "Aider edits a cloned branch, not the working app directly.", C.blue],
    ["Deterministic Validators", "AST, JSON, Jinja, JS, Java, conflict markers, and risky generated patterns.", C.teal],
    ["Reviewer Gate", "A second model checks issue alignment, missed files, nested forms, state ownership, and UI behavior.", C.purple],
    ["Human Approval", "PR creation is a deliberate final action after reviewing generated content.", C.green],
  ];
  for (let i = 0; i < left.length; i++) {
    const y = 1.62 + i * 0.86;
    slide.addShape(pptx.ShapeType.ellipse, { x: 0.9, y, w: 0.32, h: 0.32, fill: { color: left[i][2] }, line: { color: left[i][2] } });
    text(slide, String(i + 1), 1.01, y + 0.08, 0.1, 0.1, { fontSize: 6.5, bold: true, color: "FFFFFF", margin: 0, align: "center" });
    text(slide, left[i][0], 1.38, y - 0.01, 2.4, 0.16, { fontSize: 9.3, bold: true, margin: 0 });
    text(slide, left[i][1], 1.38, y + 0.22, 4.6, 0.21, { fontSize: 6.9, color: C.muted, margin: 0 });
  }

  box(slide, {
    x: 7.15,
    y: 1.55,
    w: 4.95,
    h: 1.1,
    head: "Pass path",
    body: "Issue evidence → patch → validators pass → reviewer accepts → proposal page → user approves → GitHub PR",
    fill: C.greenSoft,
    line: "BFE6D1",
    accent: C.green,
    fsHead: 10,
    fsBody: 7.1,
  });
  box(slide, {
    x: 7.15,
    y: 3.0,
    w: 4.95,
    h: 1.1,
    head: "Fail path",
    body: "Validator or reviewer rejects → visible log → targeted retry guidance → Aider gets corrected context",
    fill: C.redSoft,
    line: "F1C7C7",
    accent: C.red,
    fsHead: 10,
    fsBody: 7.1,
  });
  arrow(slide, 9.6, 2.65, 9.6, 3.0, { color: C.red, dash: true, width: 1.1 });
  arrow(slide, 7.15, 4.1, 5.95, 4.1, { color: C.red, dash: true, width: 1.1 });
  text(slide, "The loop is intentional: bad output is evidence, not a silent failure.", 6.45, 4.92, 5.3, 0.22, {
    fontSize: 8,
    color: C.ink,
    bold: true,
    margin: 0,
  });

  box(slide, {
    x: 0.55,
    y: 6.05,
    w: 12.2,
    h: 0.58,
    head: "Design principle",
    body: "Let AI accelerate discovery and draft work; keep irreversible repository actions behind deterministic checks and explicit human approval.",
    fill: C.dark,
    line: C.dark,
    dark: true,
    fsHead: 8.8,
    fsBody: 6.8,
  });
  footer(slide, 4);
}

function slide5() {
  const slide = pptx.addSlide();
  bg(slide, "F4F7FB");
  title(slide, "Practical Value and Rollout", "Why this can move from demo to real engineering support");

  const value = [
    ["Meaningful Pain", "Small bugs and UI fixes consume disproportionate engineering time because context discovery is slow."],
    ["Better Outcomes", "AI handles repo search, first-pass implementation, and review hints while people keep final judgment."],
    ["Measurable Payoff", "Shorter cycle time, cleaner handoffs, fewer missed dependent files, and a stronger review trail."],
    ["Feasible Build", "Uses Flask, GitHub API, local index, Aider CLI, validators, and review gates already wired together."],
    ["Easy Adoption", "Works with normal GitHub issues and PR review habits; can start repo-by-repo with narrow scopes."],
  ];
  for (let i = 0; i < value.length; i++) {
    const y = 1.35 + i * 0.84;
    const color = [C.blue, C.teal, C.amber, C.purple, C.green][i];
    slide.addShape(pptx.ShapeType.roundRect, {
      x: 0.72,
      y,
      w: 0.5,
      h: 0.5,
      fill: { color },
      line: { color },
    });
    text(slide, String(i + 1), 0.9, y + 0.16, 0.15, 0.12, { fontSize: 8, bold: true, color: "FFFFFF", margin: 0, align: "center" });
    text(slide, value[i][0], 1.42, y + 0.03, 2.2, 0.16, { fontSize: 10, bold: true, margin: 0 });
    text(slide, value[i][1], 3.25, y + 0.04, 7.8, 0.25, { fontSize: 7.7, color: C.muted, margin: 0 });
  }

  panel(slide, 8.95, 1.2, 3.45, 4.65, "FFFFFF");
  text(slide, "Demo talk track", 9.25, 1.48, 2.2, 0.2, { fontSize: 11.2, bold: true, margin: 0 });
  const talk = [
    "1. Show a normal issue",
    "2. Show selected files + evidence",
    "3. Run Aider and watch status",
    "4. Review diff, warnings, logs",
    "5. Approve only if patch is sane",
  ];
  for (let i = 0; i < talk.length; i++) {
    dot(slide, 9.25, 1.95 + i * 0.48, [C.blue, C.teal, C.amber, C.purple, C.green][i]);
    text(slide, talk[i], 9.48, 1.91 + i * 0.48, 2.45, 0.16, { fontSize: 7.7, color: C.ink, margin: 0 });
  }
  box(slide, {
    x: 9.25,
    y: 4.75,
    w: 2.55,
    h: 0.55,
    head: "Close with",
    body: "AI assistant for repo-aware delivery, not an auto-merge bot.",
    fill: C.mint,
    line: "BFE6DF",
    fsHead: 8,
    fsBody: 6,
  });

  footer(slide, 5);
}

slide1();
slide2();
slide3();
slide4();
slide5();

pptx.writeFile({ fileName: "GitHub_CTO_Demo_v2.pptx" });
