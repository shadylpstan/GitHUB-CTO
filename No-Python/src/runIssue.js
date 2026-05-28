import { execFileSync, execSync } from "node:child_process";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { getConfig } from "./config.js";
import { GitHubClient } from "./github.js";
import { OpenAIPlanner } from "./openaiPlanner.js";
import { classifyIssue } from "./triage.js";
import { discoverCandidateFiles, rankFiles, validateChangePath } from "./repoContext.js";
import { failureComment, issueComment, prBody } from "./commentTemplates.js";

async function main() {
  const config = getConfig();
  const github = new GitHubClient({ token: config.githubToken, repository: config.repository });
  const issueNumber = config.issueNumber || issueNumberFromEvent(config.eventPath);

  try {
    const issue = await github.issue(issueNumber);
    const comments = await github.issueComments(issueNumber);
    const defaultBranch = await github.defaultBranch();
    const triage = classifyIssue(issue, comments);
    const allFiles = discoverCandidateFiles({ maxFileBytes: config.maxFileBytes });
    const contextFiles = rankFiles({ issue, triage, files: allFiles, maxFiles: config.maxFiles });

    if (!contextFiles.length) {
      throw new Error("No readable repository files were found for context.");
    }

    const patch = await generatePatchWithBackoff({
      config,
      issue,
      comments,
      triage,
      contextFiles,
    });
    if (!patch.changes.length) {
      throw new Error(`Model returned no file changes. Summary: ${patch.summary}`);
    }

    const branch = branchName(issue);
    run("git", ["config", "user.name", "github-cto-agent"]);
    run("git", ["config", "user.email", "github-cto-agent@users.noreply.github.com"]);
    run("git", ["checkout", "-b", branch]);

    const changedFiles = [];
    for (const change of patch.changes) {
      const path = validateChangePath(change.path, allFiles);
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, change.content, "utf8");
      changedFiles.push(path);
    }

    run("git", ["add", ...changedFiles]);
    if (!hasStagedChanges()) {
      throw new Error("No staged changes were produced.");
    }

    const testResult = runTests(config.testCommand);
    run("git", ["commit", "-m", `Fix issue #${issue.number}: ${issue.title}`]);
    run("git", ["push", "--set-upstream", "origin", branch]);

    const pr = await github.createPullRequest({
      title: `Fix #${issue.number}: ${issue.title}`,
      head: branch,
      base: defaultBranch,
      body: prBody({ issue, triage, patch, changedFiles, testResult }),
    });

    await github.createIssueComment(issue.number, issueComment({ triage, pr, changedFiles, testResult }));
  } catch (error) {
    try {
      await github.createIssueComment(issueNumber, failureComment(error));
    } catch (commentError) {
      console.error("Failed to write failure comment:", commentError);
    }
    throw error;
  }
}

function issueNumberFromEvent(eventPath) {
  if (!eventPath) {
    throw new Error("GH_CTO_ISSUE_NUMBER or GITHUB_EVENT_PATH is required");
  }
  const event = JSON.parse(readFileSync(eventPath, "utf8"));
  const number = event.issue?.number || event.inputs?.issue_number;
  if (!number) {
    throw new Error("Could not resolve issue number from event payload");
  }
  return Number.parseInt(String(number), 10);
}

function branchName(issue) {
  const slug = (issue.title || "issue")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48) || "issue";
  const stamp = new Date().toISOString().replace(/[-:TZ.]/g, "").slice(0, 14);
  return `codex/issue-${issue.number}-${slug}-${stamp}`;
}

function run(command, args) {
  execFileSync(command, args, { stdio: "inherit" });
}

function hasStagedChanges() {
  try {
    execFileSync("git", ["diff", "--cached", "--quiet"]);
    return false;
  } catch {
    return true;
  }
}

function runTests(command) {
  if (!command) {
    return { command: "", status: "skipped" };
  }
  try {
    execSync(command, { stdio: "inherit", shell: true });
    return { command, status: "passed" };
  } catch (error) {
    return { command, status: `failed (${error.status || "unknown"})` };
  }
}

async function generatePatchWithBackoff({ config, issue, comments, triage, contextFiles }) {
  const attempts = [
    { files: contextFiles, chars: config.maxContextCharsPerFile },
    { files: contextFiles.slice(0, Math.max(2, Math.ceil(contextFiles.length / 2))), chars: Math.min(config.maxContextCharsPerFile, 8000) },
    { files: contextFiles.slice(0, 2), chars: Math.min(config.maxContextCharsPerFile, 5000) },
  ];

  let lastError;
  for (const attempt of attempts) {
    const planner = new OpenAIPlanner({
      apiKey: config.openaiApiKey,
      model: config.openaiModel,
      timeoutMs: config.openaiTimeoutMs,
      maxRetries: config.openaiMaxRetries,
      maxContextCharsPerFile: attempt.chars,
    });
    try {
      console.log(`Generating patch with ${attempt.files.length} file(s), ${attempt.chars} chars/file.`);
      return await planner.generatePatch({
        issue,
        comments,
        triage,
        contextFiles: attempt.files,
      });
    } catch (error) {
      lastError = error;
      if (!isOpenAIBackoffError(error)) {
        throw error;
      }
      console.warn(`OpenAI patch attempt failed, retrying with smaller context: ${error.message}`);
    }
  }
  throw lastError;
}

function isOpenAIBackoffError(error) {
  const message = String(error?.message || "");
  const code = error?.cause?.code || error?.code || "";
  return (
    error?.name === "AbortError" ||
    message.includes("fetch failed") ||
    message.includes("OpenAI API 429") ||
    message.includes("OpenAI API 500") ||
    message.includes("OpenAI API 502") ||
    message.includes("OpenAI API 503") ||
    message.includes("OpenAI API 504") ||
    message.toLowerCase().includes("timeout") ||
    code.includes("TIMEOUT") ||
    code === "UND_ERR_HEADERS_TIMEOUT"
  );
}

main();
