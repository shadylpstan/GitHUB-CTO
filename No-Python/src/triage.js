export function classifyIssue(issue, comments = []) {
  const labels = (issue.labels || []).map((label) => label.name?.toLowerCase() || "");
  const text = `${issue.title || ""}\n${issue.body || ""}\n${labels.join(" ")}`.toLowerCase();

  const intent = issueIntent(text, labels);
  const severity = scoreSeverity(text, labels, comments);

  return {
    intent,
    severity: severity.label,
    score: severity.score,
    rationale: severity.rationale,
    recommendedAction: severity.score >= 70 ? "Open an agent PR for review." : "Prepare a focused fix if context is clear.",
  };
}

function issueIntent(text, labels) {
  if (hasAny(text, ["documentation", "docs", "readme", "typo", "example text"])) {
    return { kind: "docs", confidence: 0.78, rationale: "Issue appears documentation-oriented." };
  }
  if (hasAny(text, ["feature", "enhancement", "add support", "new option", "request"])) {
    return { kind: "enhancement", confidence: 0.72, rationale: "Issue asks for new or expanded behavior." };
  }
  if (hasAny(text, ["bug", "error", "fails", "failure", "crash", "regression", "not recognized", "incorrect"])) {
    return { kind: "bug", confidence: 0.84, rationale: "Issue describes broken or incorrect behavior." };
  }
  if (labels.some((label) => ["bug", "defect"].includes(label))) {
    return { kind: "bug", confidence: 0.8, rationale: "Issue labels indicate a bug." };
  }
  return { kind: "unknown", confidence: 0.45, rationale: "Issue intent is ambiguous." };
}

function scoreSeverity(text, labels, comments) {
  let score = 25;
  const rationale = [];

  if (hasAny(text, ["security", "vulnerability", "data loss", "production down"])) {
    score += 45;
    rationale.push("High-impact language appears in the issue.");
  }
  if (hasAny(text, ["crash", "regression", "broken", "fails", "failure"])) {
    score += 25;
    rationale.push("Issue describes broken behavior.");
  }
  if (labels.some((label) => ["p0", "critical", "urgent"].includes(label))) {
    score += 35;
    rationale.push("Labels indicate urgent priority.");
  }
  if (labels.some((label) => ["bug", "defect"].includes(label))) {
    score += 15;
    rationale.push("Labels indicate a bug.");
  }
  if (comments.length > 3) {
    score += 8;
    rationale.push("Issue has active discussion.");
  }

  score = Math.max(0, Math.min(100, score));
  const label = score >= 85 ? "P0" : score >= 65 ? "P1" : score >= 40 ? "P2" : "P3";
  return { label, score, rationale: rationale.length ? rationale : ["No urgent signals detected."] };
}

function hasAny(text, terms) {
  return terms.some((term) => text.includes(term));
}
