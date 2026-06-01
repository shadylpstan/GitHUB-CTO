const pptxgen = require("pptxgenjs");

async function main() {
const pptx = new pptxgen();
pptx.layout = "LAYOUT_WIDE";
pptx.author = "GitHub CTO";
pptx.company = "GitHub CTO";
pptx.subject = "AI-assisted GitHub issue to PR workflow";
pptx.title = "GitHub CTO Demo";
pptx.lang = "en-US";
pptx.theme = {
  headFontFace: "Trebuchet MS",
  bodyFontFace: "Calibri",
  lang: "en-US",
};
const MAX_SLIDES = Number(process.env.MAX_SLIDES || 6);

const C = {
  ink: "17211F",
  charcoal: "16201D",
  deep: "0F1715",
  green: "1F7A54",
  mint: "8BE0B2",
  pale: "F4F7F2",
  line: "C9D8D0",
  gold: "CC7A12",
  red: "C93325",
  muted: "6E7D76",
  white: "FFFFFF",
};

function addFooter(slide, n) {
  slide.addText(`GitHub CTO demo / ${n}`, {
    x: 11.25, y: 7.05, w: 1.45, h: 0.18,
    fontFace: "Calibri", fontSize: 8.5, color: "B8C8C0",
    align: "right", margin: 0,
  });
}

function setBg(slide, color) {
  slide.addShape(pptx.ShapeType.rect, {
    x: 0, y: 0, w: 13.33, h: 7.5,
    fill: { color },
    line: { color },
  });
}

function title(slide, text, dark = false) {
  slide.addText(text, {
    x: 0.55, y: 0.45, w: 7.8, h: 0.45,
    fontFace: "Trebuchet MS", fontSize: 25,
    bold: true, color: dark ? C.white : C.ink,
    margin: 0, fit: "shrink",
  });
}

function pill(slide, text, x, y, w, fill, color = C.white) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x, y, w, h: 0.34,
    rectRadius: 0.08,
    fill: { color: fill },
    line: { color: fill },
  });
  slide.addText(text, {
    x: x + 0.08, y: y + 0.075, w: w - 0.16, h: 0.14,
    fontSize: 8.5, bold: true, color, align: "center", margin: 0,
  });
}

function card(slide, x, y, w, h, header, body, opts = {}) {
  const shapeOpts = {
    x, y, w, h,
    rectRadius: 0.08,
    fill: { color: opts.fill || C.white },
    line: { color: opts.line || "D8E2DC", width: 1 },
  };
  if (opts.shadow !== false) {
    shapeOpts.shadow = { type: "outer", color: "000000", blur: 1, offset: 1, angle: 45, opacity: 0.12 };
  }
  slide.addShape(pptx.ShapeType.roundRect, {
    ...shapeOpts,
  });
  if (opts.badge) {
    slide.addShape(pptx.ShapeType.ellipse, {
      x: x + 0.18, y: y + 0.22, w: 0.36, h: 0.36,
      fill: { color: opts.badgeColor || C.green },
      line: { color: opts.badgeColor || C.green },
    });
    slide.addText(opts.badge, {
      x: x + 0.18, y: y + 0.31, w: 0.36, h: 0.1,
      fontSize: 8, bold: true, color: C.white, align: "center", margin: 0,
    });
  }
  slide.addText(header, {
    x: x + 0.22 + (opts.badge ? 0.45 : 0), y: y + 0.22, w: w - 0.44 - (opts.badge ? 0.45 : 0), h: 0.34,
    fontSize: 14, bold: true, color: opts.headerColor || C.ink,
    margin: 0, fit: "shrink",
  });
  slide.addText(body, {
    x: x + 0.22, y: y + 0.72, w: w - 0.44, h: Math.max(0.18, h - 0.9),
    fontSize: 10.7, color: opts.bodyColor || C.muted,
    breakLine: false, margin: 0.02, fit: "shrink", valign: "top",
  });
}

function arrow(slide, x, y, w) {
  slide.addShape(pptx.ShapeType.chevron, {
    x, y, w, h: 0.34,
    fill: { color: C.mint },
    line: { color: C.mint },
    rotate: 0,
  });
}

// Slide 1
if (MAX_SLIDES >= 1) {
  const s = pptx.addSlide();
  setBg(s, C.deep);
  s.addShape(pptx.ShapeType.rect, { x: 0, y: 0, w: 4.9, h: 7.5, fill: { color: C.green }, line: { color: C.green } });
  s.addShape(pptx.ShapeType.rect, { x: 4.9, y: 0, w: 8.43, h: 7.5, fill: { color: C.deep }, line: { color: C.deep } });
  s.addText("GitHub CTO", {
    x: 0.72, y: 0.72, w: 3.3, h: 0.55,
    color: C.white, fontSize: 26, bold: true, margin: 0,
  });
  s.addText("AI-assisted issue-to-PR workflow", {
    x: 0.74, y: 1.28, w: 3.4, h: 0.28,
    color: "D9F5E7", fontSize: 12.5, margin: 0,
  });
  s.addText("Turn GitHub issues into reviewable, validated pull requests while keeping humans in control.", {
    x: 5.5, y: 1.16, w: 6.55, h: 1.45,
    color: C.white, fontSize: 29, bold: true,
    fontFace: "Trebuchet MS", margin: 0, fit: "shrink",
  });
  s.addText("Demo focus: relevant problem, AI leverage, workflow impact, practical architecture, and adoption path.", {
    x: 5.54, y: 3.03, w: 5.5, h: 0.55,
    color: "C6D4CF", fontSize: 13, margin: 0,
  });
  ["Issue intake", "Repo evidence", "Aider edits", "Review gate", "Human approval"].forEach((t, i) => {
    pill(s, t, 5.55 + (i % 3) * 1.75, 4.35 + Math.floor(i / 3) * 0.55, 1.5, i === 2 ? C.gold : C.green);
  });
  addFooter(s, 1);
}

// Slide 2
if (MAX_SLIDES >= 2) {
  const s = pptx.addSlide();
  setBg(s, C.pale);
  title(s, "The Engineering Backlog Gap");
  card(s, 0.7, 1.35, 3.65, 4.35, "Today’s manual loop", "Developers translate issues into code by reading context, hunting files, making edits, running checks, and preparing pull requests.", { badge: "1", badgeColor: C.red });
  card(s, 4.85, 1.35, 3.65, 4.35, "Where time leaks", "Small changes still require repo navigation, ownership reasoning, formatting care, validation, and PR hygiene.", { badge: "2", badgeColor: C.gold });
  card(s, 9.0, 1.35, 3.65, 4.35, "Why it matters", "Backlog cleanup slows down, repeated issues sit longer, and engineers lose focus to routine context gathering.", { badge: "3", badgeColor: C.green });
  s.addText("Meaningful target: reduce the issue-to-reviewable-PR cycle without removing human judgment.", {
    x: 0.75, y: 6.25, w: 11.6, h: 0.4,
    fontSize: 15, bold: true, color: C.ink, margin: 0,
  });
  addFooter(s, 2);
}

// Slide 3
if (MAX_SLIDES >= 3) {
  const s = pptx.addSlide();
  setBg(s, C.deep);
  title(s, "High-Level Agent Flow", true);
  const y = 2.05;
  const steps = [
    ["GitHub Issue", "Title, body, comments, labels"],
    ["Repo Evidence", "Index, files, logs, git state"],
    ["Plan", "Root cause, owner files, constraints"],
    ["Aider Edit", "Isolated workspace diff"],
    ["Quality Gate", "Validators + reviewer feedback"],
    ["Human Review", "Approve only sane PRs"],
  ];
  steps.forEach((step, i) => {
    const x = 0.45 + i * 2.05;
    s.addShape(pptx.ShapeType.roundRect, {
      x, y, w: 1.55, h: 1.55, rectRadius: 0.08,
      fill: { color: i === 3 ? C.gold : C.green },
      line: { color: "23352F", width: 1 },
    });
    s.addText(step[0], { x: x + 0.12, y: y + 0.25, w: 1.31, h: 0.26, fontSize: 11.5, bold: true, color: C.white, align: "center", margin: 0, fit: "shrink" });
    s.addText(step[1], { x: x + 0.13, y: y + 0.72, w: 1.29, h: 0.43, fontSize: 8.5, color: "E2F3EA", align: "center", margin: 0, fit: "shrink" });
    if (i < steps.length - 1) arrow(s, x + 1.62, y + 0.62, 0.38);
  });
  s.addShape(pptx.ShapeType.line, {
    x: 5.35, y: 4.56, w: 1.7, h: 0,
    line: { color: C.mint, width: 2, beginArrowType: "triangle" },
  });
  s.addShape(pptx.ShapeType.line, {
    x: 7.05, y: 4.56, w: 1.7, h: 0,
    line: { color: C.mint, width: 2, endArrowType: "triangle" },
  });
  s.addText("Retry loop: reviewer or validator failures become targeted feedback for another Aider attempt.", {
    x: 4.0, y: 5.35, w: 5.45, h: 0.55,
    color: "C6D4CF", fontSize: 12.5, bold: true, align: "center", margin: 0,
  });
  card(s, 0.8, 6.17, 11.7, 0.55, "Design principle", "AI drafts the patch, but deterministic checks, reviewer reasoning, and human approval decide whether it should become a PR.", { fill: "20312C", line: "345149", headerColor: C.mint, bodyColor: "D8E9E1", shadow: false });
  addFooter(s, 3);
}

// Slide 4
if (MAX_SLIDES >= 4) {
  const s = pptx.addSlide();
  setBg(s, C.pale);
  title(s, "Where AI Changes the Outcome");
  card(s, 0.72, 1.25, 3.75, 2.0, "Context discovery", "Ranks relevant files, reads code metadata, and finds likely ownership without manual repo spelunking.", { badge: "AI", badgeColor: C.green });
  card(s, 4.78, 1.25, 3.75, 2.0, "Patch drafting", "Aider edits inside an isolated clone, preserving a reviewable diff instead of directly touching GitHub.", { badge: "AI", badgeColor: C.gold });
  card(s, 8.84, 1.25, 3.75, 2.0, "Review reasoning", "A second agent checks whether the patch solves the issue, updates connection points, and avoids shallow fixes.", { badge: "AI", badgeColor: C.green });
  card(s, 1.25, 4.25, 4.85, 1.55, "Learning from mistakes", "Failures are stored as lessons so future runs can avoid repeated patterns like competing UI state handlers.", { fill: "EEF7F1", line: "BFD8CA", headerColor: C.ink });
  card(s, 7.1, 4.25, 4.85, 1.55, "Human remains in control", "The proposal screen shows plan, reviewer gate, diffs, and editable file content before PR creation.", { fill: "FFF5E8", line: "E5C490", headerColor: C.ink });
  addFooter(s, 4);
}

// Slide 5
if (MAX_SLIDES >= 5) {
  const s = pptx.addSlide();
  setBg(s, C.deep);
  title(s, "Expected Value in Practice", true);
  const stats = [
    ["Minutes", "from issue to reviewable draft for routine fixes"],
    ["Higher signal", "through file ranking, plan visibility, and validation"],
    ["Lower toil", "less manual context gathering and PR boilerplate"],
    ["Safer adoption", "human approval before GitHub changes"],
  ];
  stats.forEach((st, i) => {
    const x = 0.75 + (i % 2) * 6.0;
    const y = 1.45 + Math.floor(i / 2) * 2.15;
    s.addShape(pptx.ShapeType.rect, { x, y, w: 5.25, h: 1.5, fill: { color: i === 0 ? C.green : "20312C" }, line: { color: "3E5E54", width: 1 } });
    s.addText(st[0], { x: x + 0.3, y: y + 0.22, w: 4.6, h: 0.35, fontSize: 22, bold: true, color: i === 0 ? C.white : C.mint, margin: 0, fit: "shrink" });
    s.addText(st[1], { x: x + 0.32, y: y + 0.78, w: 4.4, h: 0.35, fontSize: 11.5, color: "D8E9E1", margin: 0 });
  });
  s.addText("The value is not full autonomy. The value is faster, better-prepared human review.", {
    x: 1.15, y: 6.35, w: 10.9, h: 0.35,
    fontSize: 16, bold: true, color: C.white, align: "center", margin: 0,
  });
  addFooter(s, 5);
}

// Slide 6
if (MAX_SLIDES >= 6) {
  const s = pptx.addSlide();
  setBg(s, C.pale);
  title(s, "Ready for a Controlled Rollout");
  const rows = [
    ["GitHub-native workflow", "Works from issues, branches, diffs, and pull requests that teams already use."],
    ["Guarded automation", "No direct merge path: proposals are validated and approved by a human."],
    ["Practical scaling path", "Start with UI bugs and maintenance issues, then expand as validators and lessons mature."],
    ["Extensible architecture", "Planner, Aider worker, reviewer, validators, memory, and browser checks can evolve independently."],
  ];
  rows.forEach((r, i) => {
    const y = 1.25 + i * 1.2;
    s.addShape(pptx.ShapeType.ellipse, { x: 0.82, y: y + 0.05, w: 0.45, h: 0.45, fill: { color: i % 2 ? C.gold : C.green }, line: { color: i % 2 ? C.gold : C.green } });
    s.addText(String(i + 1), { x: 0.82, y: y + 0.17, w: 0.45, h: 0.1, fontSize: 9.5, bold: true, color: C.white, align: "center", margin: 0 });
    s.addText(r[0], { x: 1.55, y, w: 4.0, h: 0.28, fontSize: 15, bold: true, color: C.ink, margin: 0 });
    s.addText(r[1], { x: 1.55, y: y + 0.36, w: 10.2, h: 0.3, fontSize: 11.5, color: C.muted, margin: 0 });
  });
  s.addShape(pptx.ShapeType.rect, { x: 0, y: 6.55, w: 13.33, h: 0.95, fill: { color: C.green }, line: { color: C.green } });
  s.addText("Demo close: GitHub CTO converts a real issue into a gated, reviewable PR proposal.", {
    x: 0.85, y: 6.85, w: 11.6, h: 0.25,
    fontSize: 15, bold: true, color: C.white, align: "center", margin: 0,
  });
  addFooter(s, 6);
}

await pptx.writeFile({ fileName: "GitHub_CTO_Demo.pptx" });
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
