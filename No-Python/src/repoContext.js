import { execFileSync } from "node:child_process";
import { readFileSync, statSync } from "node:fs";
import { extname, basename } from "node:path";

const textExtensions = new Set([
  ".js",
  ".jsx",
  ".ts",
  ".tsx",
  ".mjs",
  ".cjs",
  ".json",
  ".css",
  ".scss",
  ".html",
  ".md",
  ".yml",
  ".yaml",
  ".toml",
  ".ini",
  ".txt",
  ".sh",
  ".sql",
  ".go",
  ".rs",
  ".java",
  ".rb",
  ".php",
  ".cs",
]);

const skipParts = new Set([
  ".git",
  ".venv",
  "venv",
  "__pycache__",
  ".pytest_cache",
  ".mypy_cache",
  ".ruff_cache",
  "node_modules",
  "No-Python",
  "dist",
  "build",
  "vendor",
  "coverage",
]);

const skipNames = new Set(["package-lock.json", "yarn.lock", "pnpm-lock.yaml"]);
const skipSuffixes = new Set([".lock", ".log", ".csv", ".xls", ".xlsx", ".doc", ".docx", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".zip"]);

export function discoverCandidateFiles({ maxFileBytes }) {
  const output = execFileSync("git", ["ls-files"], { encoding: "utf8" });
  return output
    .split(/\r?\n/)
    .filter(Boolean)
    .filter((path) => shouldReadPath(path, maxFileBytes));
}

export function rankFiles({ issue, triage, files, maxFiles }) {
  const issueText = `${issue.title || ""}\n${issue.body || ""}`;
  const terms = issueTerms(issueText);
  const roles = issueRoles(issueText);

  const scored = files.map((path) => {
    const content = safeRead(path);
    const normalizedPath = path.toLowerCase();
    const normalizedContent = content.toLowerCase();
    const fileRoles = rolesForFile(path, normalizedContent);
    let score = pathScore(path, triage.intent.kind);
    const reasons = [];

    const contentHits = terms.filter((term) => normalizedContent.includes(term));
    if (contentHits.length) {
      score += Math.min(contentHits.length, 8) * 10;
      reasons.push(`content matches: ${contentHits.slice(0, 5).join(", ")}`);
    }

    const pathHits = terms.filter((term) => normalizedPath.includes(term));
    if (pathHits.length) {
      score += Math.min(pathHits.length, 4) * 4;
      reasons.push(`path matches: ${pathHits.slice(0, 3).join(", ")}`);
    }

    for (const role of roles) {
      if (fileRoles.has(role)) {
        score += 24;
        reasons.push(`matches role: ${role}`);
      }
    }

    return { path, score, reasons };
  });

  return scored
    .sort((left, right) => right.score - left.score)
    .slice(0, maxFiles)
    .map((item) => ({ ...item, content: safeRead(item.path), summary: summarizeFile(item.path, safeRead(item.path)) }));
}

export function validateChangePath(path, allowedFiles) {
  const normalized = path.replaceAll("\\", "/").replace(/^\/+/, "");
  if (!normalized || normalized.includes("../") || normalized.startsWith("..")) {
    throw new Error(`Unsafe change path: ${path}`);
  }
  const isExisting = allowedFiles.includes(normalized);
  const isReasonableNewFile = shouldReadPath(normalized, Number.MAX_SAFE_INTEGER, { allowMissing: true });
  if (!isExisting && !isReasonableNewFile) {
    throw new Error(`Refusing unsupported new file path: ${path}`);
  }
  return normalized;
}

function shouldReadPath(path, maxFileBytes, options = {}) {
  const normalized = path.replaceAll("\\", "/");
  const parts = normalized.split("/");
  const name = basename(normalized);
  const suffix = extname(normalized).toLowerCase();
  if (parts.some((part) => skipParts.has(part))) return false;
  if (skipNames.has(name)) return false;
  if (skipSuffixes.has(suffix)) return false;
  if (!textExtensions.has(suffix)) return false;
  if (options.allowMissing) return true;
  try {
    return statSync(normalized).size <= maxFileBytes;
  } catch {
    return false;
  }
}

function pathScore(path, intent) {
  const normalized = path.replaceAll("\\", "/").toLowerCase();
  const name = basename(normalized);
  let score = 0;

  if (["bug", "enhancement"].includes(intent)) {
    if (normalized.startsWith("src/") || normalized.startsWith("lib/") || normalized.startsWith("app/")) score += 50;
    if (normalized.includes("/test") || normalized.startsWith("test") || name.includes(".test.")) score += 25;
    if (normalized.startsWith("docs/") || normalized.includes("example")) score -= 45;
  } else if (intent === "docs") {
    if (normalized.startsWith("docs/") || suffixIs(normalized, [".md"])) score += 55;
  } else {
    if (suffixIs(normalized, [".js", ".ts", ".tsx", ".jsx"])) score += 20;
  }

  if (["index.js", "main.js", "app.js", "server.js"].includes(name)) score += 8;
  return score;
}

function issueTerms(text) {
  const stop = new Set(["there", "should", "would", "could", "application", "option", "with", "from", "that", "this"]);
  const words = text.toLowerCase().match(/[a-zA-Z_/-]{4,}/g) || [];
  return [...new Set(words.map((word) => word.replace(/^[-_/]+|[-_/]+$/g, "")).filter((word) => word && !stop.has(word)))].slice(0, 24);
}

function issueRoles(text) {
  const lowered = text.toLowerCase();
  const roles = new Set();
  if (["button", "option", "ui", "screen", "page", "dashboard"].some((term) => lowered.includes(term))) roles.add("ui_surface");
  if (["route", "endpoint", "post", "request"].some((term) => lowered.includes(term))) roles.add("route_owner");
  if (["delete", "remove", "store", "save", "database", "index"].some((term) => lowered.includes(term))) roles.add("data_access");
  return roles;
}

function rolesForFile(path, content) {
  const normalized = path.replaceAll("\\", "/").toLowerCase();
  const roles = new Set();
  if (normalized.includes("template") || normalized.endsWith(".tsx") || normalized.endsWith(".jsx")) roles.add("ui_surface");
  if (["@app.route", "express.", "router.", "fastify.", "app.get", "app.post"].some((term) => content.includes(term))) roles.add("route_owner");
  if (["sqlite", "select ", "insert ", "update ", "delete ", "prisma", "sequelize"].some((term) => content.includes(term))) roles.add("data_access");
  return roles;
}

function summarizeFile(path, content) {
  const lines = content.split(/\r?\n/);
  const symbols = [];
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].trim();
    if (/^(export\s+)?(async\s+)?function\s+\w+/.test(line) || /^class\s+\w+/.test(line) || /^const\s+\w+\s*=/.test(line)) {
      symbols.push(`line ${index + 1}: ${line.slice(0, 140)}`);
    }
    if (symbols.length >= 24) break;
  }
  return [`path: ${path}`, `lines: ${lines.length}`, `chars: ${content.length}`, "notable symbols:", symbols.join("\n") || "No obvious symbols detected."].join("\n");
}

function safeRead(path) {
  return readFileSync(path, "utf8");
}

function suffixIs(path, suffixes) {
  return suffixes.some((suffix) => path.endsWith(suffix));
}
