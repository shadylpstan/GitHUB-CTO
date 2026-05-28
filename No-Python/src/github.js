const apiBase = "https://api.github.com";

export class GitHubClient {
  constructor({ token, repository }) {
    const [owner, repo] = repository.split("/");
    if (!owner || !repo) {
      throw new Error("GITHUB_REPOSITORY must look like owner/repo");
    }
    this.token = token;
    this.repository = repository;
  }

  async issue(number) {
    return this.request("GET", `/repos/${this.repository}/issues/${number}`);
  }

  async issueComments(number) {
    return this.request("GET", `/repos/${this.repository}/issues/${number}/comments?per_page=100`);
  }

  async createIssueComment(number, body) {
    return this.request("POST", `/repos/${this.repository}/issues/${number}/comments`, { body });
  }

  async createPullRequest({ title, head, base, body }) {
    return this.request("POST", `/repos/${this.repository}/pulls`, { title, head, base, body });
  }

  async defaultBranch() {
    const repo = await this.request("GET", `/repos/${this.repository}`);
    return repo.default_branch;
  }

  async request(method, path, body = undefined) {
    const response = await fetch(`${apiBase}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${this.token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "github-cto-no-python",
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });

    if (response.status === 204) {
      return null;
    }

    const text = await response.text();
    const payload = text ? JSON.parse(text) : {};
    if (!response.ok) {
      throw new Error(`GitHub API ${response.status}: ${payload.message || text}`);
    }
    return payload;
  }
}
