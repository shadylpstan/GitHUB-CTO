import { readFileSync } from "node:fs";

export class OpenAIPlanner {
  constructor({ apiKey, model }) {
    this.apiKey = apiKey;
    this.model = model;
    this.systemPrompt = readFileSync(new URL("../prompts/patch-system.md", import.meta.url), "utf8");
  }

  async generatePatch({ issue, comments, triage, contextFiles }) {
    const response = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${this.apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: this.model,
        temperature: 0.2,
        response_format: { type: "json_object" },
        messages: [
          { role: "system", content: this.systemPrompt },
          {
            role: "user",
            content: buildUserPrompt({ issue, comments, triage, contextFiles }),
          },
        ],
      }),
    });

    const payload = await response.json();
    if (!response.ok) {
      throw new Error(`OpenAI API ${response.status}: ${payload.error?.message || JSON.stringify(payload)}`);
    }

    const raw = payload.choices?.[0]?.message?.content;
    if (!raw) {
      throw new Error("OpenAI returned no content");
    }
    return validatePatch(JSON.parse(raw));
  }
}

function buildUserPrompt({ issue, comments, triage, contextFiles }) {
  const discussion = comments
    .slice(-8)
    .map((comment) => `- ${comment.user?.login || "user"}: ${(comment.body || "").slice(0, 1200)}`)
    .join("\n");

  const files = contextFiles
    .map((file) => {
      return [
        `--- FILE: ${file.path} ---`,
        "# Ranking evidence",
        file.reasons.length ? file.reasons.join("; ") : "Selected by repository structure.",
        "# Local structural summary",
        file.summary,
        "# Content",
        trim(file.content, 24000),
        "--- END FILE ---",
      ].join("\n");
    })
    .join("\n\n");

  return [
    `GitHub issue #${issue.number}: ${issue.title}`,
    "",
    issue.body || "No issue body provided.",
    "",
    `Triage: ${triage.severity} (${triage.score}/100), intent=${triage.intent.kind}`,
    `Triage rationale: ${triage.rationale.join("; ")}`,
    "",
    "Recent discussion:",
    discussion || "No comments.",
    "",
    "Relevant repository context:",
    files,
  ].join("\n");
}

function validatePatch(patch) {
  if (!patch || typeof patch !== "object") {
    throw new Error("Patch response must be an object");
  }
  if (!Array.isArray(patch.changes)) {
    throw new Error("Patch response must include changes array");
  }
  return {
    summary: String(patch.summary || "No summary provided."),
    testPlan: String(patch.test_plan || patch.testPlan || "Review the PR diff and run the repository test suite."),
    changes: patch.changes.map((change) => {
      if (!change.path || typeof change.content !== "string") {
        throw new Error("Each change must include path and content");
      }
      return { path: String(change.path), content: change.content };
    }),
  };
}

function trim(content, maxChars) {
  if (content.length <= maxChars) return content;
  const head = Math.floor(maxChars / 2);
  const tail = maxChars - head;
  return `${content.slice(0, head)}\n\n# ... content trimmed for context budget ...\n\n${content.slice(-tail)}`;
}
