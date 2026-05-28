export function getConfig() {
  return {
    openaiApiKey: requiredEnv("OPENAI_API_KEY"),
    openaiModel: process.env.OPENAI_MODEL || "gpt-4.1-mini",
    githubToken: requiredEnv("GITHUB_TOKEN"),
    repository: requiredEnv("GITHUB_REPOSITORY"),
    eventPath: process.env.GITHUB_EVENT_PATH || "",
    issueNumber: numberEnv("GH_CTO_ISSUE_NUMBER"),
    maxFiles: numberEnv("GH_CTO_MAX_FILES", 8),
    maxFileBytes: numberEnv("GH_CTO_MAX_FILE_BYTES", 80000),
    maxContextCharsPerFile: numberEnv("GH_CTO_MAX_CONTEXT_CHARS_PER_FILE", 12000),
    openaiTimeoutMs: numberEnv("GH_CTO_OPENAI_TIMEOUT_MS", 180000),
    openaiMaxRetries: numberEnv("GH_CTO_OPENAI_MAX_RETRIES", 2),
    testCommand: process.env.GH_CTO_TEST_COMMAND || "",
  };
}

function requiredEnv(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is required`);
  }
  return value;
}

function numberEnv(name, fallback = undefined) {
  const value = process.env[name];
  if (!value && fallback !== undefined) {
    return fallback;
  }
  const parsed = Number.parseInt(value || "", 10);
  if (!Number.isFinite(parsed)) {
    throw new Error(`${name} must be a number`);
  }
  return parsed;
}
