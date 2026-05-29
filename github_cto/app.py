from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for

from .agent_loop import AgentLoopConfig, IterativeAgentLoop
from .aider_backend import AiderBackend, AiderConfig, AiderRunError
from .aider_jobs import AiderJobRegistry
from .ai import CodexEngineeringManager, CodexTimeout, CodexTransientError, PatchReviewAgent
from .config import Config
from .github_client import GitHubClient, GitHubError
from .index_jobs import IndexJobRegistry
from .proposals import ProposalStore, attach_diffs
from .repo_index import OpenAIEmbedder, OpenAIFileSummarizer, RepositoryIndex
from .triage import triage_issue
from .validators import ProposalValidationError, validate_proposal_changes
from .workflow import GitHubCTOWorkflow


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    setup_logging(app)
    index_jobs = IndexJobRegistry()
    aider_jobs = AiderJobRegistry()

    def current_settings() -> tuple[str, str]:
        token = session.get("github_token") or app.config["GITHUB_TOKEN"]
        repo = session.get("github_repo") or app.config["GITHUB_REPOSITORY"]
        return token, repo

    def branch_settings(default_branch: str, branches: list[str] | None = None) -> dict[str, str]:
        available = set(branches or [])
        read_branch = (session.get("github_read_branch") or default_branch).strip()
        target_branch = (session.get("github_target_branch") or default_branch).strip()
        if available and read_branch not in available:
            read_branch = default_branch
        if available and target_branch not in available:
            target_branch = default_branch
        return {"read_branch": read_branch, "target_branch": target_branch, "default_branch": default_branch}

    def posted_branch_settings(github: GitHubClient) -> dict[str, str]:
        default_branch = github.default_branch()
        branches = github.list_branches()
        settings = branch_settings(default_branch, branches)
        read_branch = request.form.get("read_branch", settings["read_branch"]).strip() or default_branch
        target_branch = request.form.get("target_branch", settings["target_branch"]).strip() or default_branch
        if read_branch not in branches:
            raise ValueError(f"Unknown read branch: {read_branch}")
        if target_branch not in branches:
            raise ValueError(f"Unknown PR target branch: {target_branch}")
        session["github_read_branch"] = read_branch
        session["github_target_branch"] = target_branch
        return {"read_branch": read_branch, "target_branch": target_branch, "default_branch": default_branch}

    def make_github() -> GitHubClient:
        token, repo = current_settings()
        return GitHubClient(token=token, repo=repo)

    def make_github_from_values(token: str, repo: str) -> GitHubClient:
        return GitHubClient(token=token, repo=repo)

    def make_workflow() -> GitHubCTOWorkflow:
        github = make_github()
        planner = CodexEngineeringManager(
            app.config["OPENAI_API_KEY"],
            app.config["OPENAI_MODEL"],
            planning_timeout=app.config["OPENAI_PLANNING_TIMEOUT"],
            patch_timeout=app.config["OPENAI_PATCH_TIMEOUT"],
            max_retries=app.config["OPENAI_MAX_RETRIES"],
        )
        return GitHubCTOWorkflow(
            github=github,
            planner=planner,
            max_repo_files=app.config["MAX_REPO_FILES"],
            max_file_bytes=app.config["MAX_FILE_BYTES"],
            default_selected_files=app.config["DEFAULT_SELECTED_FILES"],
            max_selected_files=app.config["MAX_SELECTED_FILES"],
            max_context_chars_per_file=app.config["MAX_CONTEXT_CHARS_PER_FILE"],
            max_parallel_fetches=app.config["MAX_PARALLEL_FETCHES"],
            enable_file_summaries=app.config["ENABLE_FILE_SUMMARIES"],
            repo_index=make_repo_index(),
        )

    def make_repo_index() -> RepositoryIndex:
        embedder = OpenAIEmbedder(app.config["OPENAI_API_KEY"], app.config["OPENAI_EMBEDDING_MODEL"])
        summarizer = OpenAIFileSummarizer(
            app.config["OPENAI_API_KEY"],
            app.config["FILE_METADATA_MODEL"],
            timeout=app.config["FILE_METADATA_TIMEOUT"],
            enabled=app.config["ENABLE_AI_FILE_METADATA"],
        )
        return RepositoryIndex(app.instance_path + "/repo_index.sqlite3", embedder, file_summarizer=summarizer)

    def proposal_store() -> ProposalStore:
        return ProposalStore(app.instance_path + "/proposals")

    def make_agent_loop() -> IterativeAgentLoop:
        return IterativeAgentLoop(
            workflow=make_workflow(),
            config=AgentLoopConfig(
                max_steps=app.config["AGENT_MAX_STEPS"],
                test_command=app.config["AGENT_TEST_COMMAND"],
                test_timeout=app.config["AGENT_TEST_TIMEOUT"],
                openai_timeout=app.config["AGENT_OPENAI_TIMEOUT"],
                openai_max_retries=app.config["AGENT_OPENAI_MAX_RETRIES"],
                max_context_chars_per_file=min(app.config["MAX_CONTEXT_CHARS_PER_FILE"], 6000),
            ),
        )

    def make_aider_backend() -> AiderBackend:
        return AiderBackend(
            repo_root=app.root_path + "/..",
            workspace_root=app.instance_path + "/aider_runs",
            config=AiderConfig(
                command=app.config["AIDER_COMMAND"],
                model=app.config["AIDER_MODEL"],
                timeout=app.config["AIDER_TIMEOUT"],
                test_command=app.config["AIDER_TEST_COMMAND"],
                keep_runs=app.config["AIDER_KEEP_RUNS"],
            ),
        )

    @app.context_processor
    def inject_globals():
        token, repo = current_settings()
        return {
            "configured_repo": repo,
            "has_github_token": bool(token),
            "has_openai_key": bool(app.config["OPENAI_API_KEY"]),
        }

    @app.route("/", methods=["GET", "POST"])
    def index():
        if request.method == "POST":
            session["github_token"] = request.form.get("github_token", "").strip()
            session["github_repo"] = request.form.get("github_repo", "").strip()
            flash("GitHub connection settings saved for this session.", "success")
            return redirect(url_for("dashboard"))
        token, repo = current_settings()
        if token and repo:
            return redirect(url_for("dashboard"))
        return render_template("index.html")

    @app.route("/connection", methods=["GET", "POST"])
    def connection():
        if request.method == "POST":
            session["github_token"] = request.form.get("github_token", "").strip()
            session["github_repo"] = request.form.get("github_repo", "").strip()
            flash("GitHub connection settings saved for this session.", "success")
            return redirect(url_for("dashboard"))
        return render_template("index.html", force_connection=True)

    @app.route("/connection/reset", methods=["POST"])
    def reset_connection():
        session.pop("github_token", None)
        session.pop("github_repo", None)
        session.pop("github_read_branch", None)
        session.pop("github_target_branch", None)
        flash("Browser override cleared. Using .env settings again.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/branch-settings", methods=["POST"])
    def update_branch_settings():
        next_url = request.form.get("next") or url_for("dashboard")
        if not next_url.startswith("/"):
            next_url = url_for("dashboard")
        try:
            github = make_github()
            settings = posted_branch_settings(github)
            flash(
                f"Branch settings saved. Reading {settings['read_branch']} and opening PRs into {settings['target_branch']}.",
                "success",
            )
        except Exception as exc:
            flash(str(exc), "error")
        return redirect(next_url)

    @app.route("/dashboard")
    def dashboard():
        try:
            github = make_github()
            repo = github.repository()
            user = github.current_user()
            branches = github.list_branches()
            settings = branch_settings(repo["default_branch"], branches)
            app.logger.info("Loading dashboard for repo=%s user=%s", github.repo.full_name, user.get("login"))
            issues = github.list_issues(limit=30)
            repo_index = make_repo_index()
            index_stats = repo_index.stats(github.repo.full_name, settings["read_branch"])
            indexed_files = repo_index.indexed_files(github.repo.full_name, settings["read_branch"])
            triaged = []
            for issue in issues:
                triaged.append({"issue": issue, "triage": triage_issue(issue)})
            return render_template(
                "dashboard.html",
                repo=repo,
                user=user,
                triaged=triaged,
                index_stats=index_stats,
                indexed_files=indexed_files,
                index_job=index_jobs.snapshot(),
                branches=branches,
                branch_settings=settings,
            )
        except (ValueError, GitHubError) as exc:
            flash(str(exc), "error")
            return redirect(url_for("index"))

    @app.route("/issues.json")
    def issues_json():
        try:
            github = make_github()
            issues = github.list_issues(limit=30)
            rows = []
            for issue in issues:
                triage = triage_issue(issue)
                rows.append(
                    {
                        "number": issue["number"],
                        "title": issue["title"],
                        "url": url_for("issue_detail", issue_number=issue["number"]),
                        "severity": triage.severity,
                        "score": triage.score,
                        "recommended_action": triage.recommended_action,
                    }
                )
            return jsonify({"issues": rows})
        except Exception as exc:
            app.logger.exception("Failed to poll issues")
            return jsonify({"error": str(exc), "issues": []}), 500

    @app.route("/index/rebuild", methods=["POST"])
    def rebuild_index():
        if index_jobs.is_running():
            flash("Repository index rebuild is already running.", "error")
            return redirect(url_for("dashboard"))

        try:
            token, repo_name = current_settings()
            github = make_github()
            repo = github.repository()
            branches = github.list_branches()
            branch = branch_settings(repo["default_branch"], branches)["read_branch"]
            index_jobs.start(github.repo.full_name, branch)
            app.logger.info("Queued index rebuild for %s on %s", github.repo.full_name, branch)

            worker = threading.Thread(
                target=_run_index_rebuild,
                args=(app, index_jobs, token, repo_name, branch),
                daemon=True,
            )
            worker.start()
            flash("Repository index rebuild started. Progress will update below.", "success")
        except Exception as exc:
            app.logger.exception("Failed to start index rebuild")
            index_jobs.fail(str(exc))
            flash(str(exc), "error")
        return redirect(url_for("dashboard"))

    @app.route("/index/delete", methods=["POST"])
    def delete_index():
        if index_jobs.is_running():
            flash("Repository index rebuild is running. Wait for it to finish before deleting the index.", "error")
            return redirect(url_for("dashboard"))

        try:
            github = make_github()
            repo = github.repository()
            branches = github.list_branches()
            branch = branch_settings(repo["default_branch"], branches)["read_branch"]
            deleted = make_repo_index().delete_index(github.repo.full_name, branch)
            app.logger.info("Deleted repository index repo=%s branch=%s rows=%s", github.repo.full_name, branch, deleted)
            flash(f"Deleted repository index for {github.repo.full_name} on {branch}. Removed {deleted} chunk(s).", "success")
        except Exception as exc:
            app.logger.exception("Failed to delete repository index")
            flash(str(exc), "error")
        return redirect(url_for("dashboard"))

    @app.route("/index/status")
    def index_status():
        return jsonify(index_jobs.snapshot())

    @app.route("/index/files")
    def index_files():
        try:
            github = make_github()
            repo = github.repository()
            branches = github.list_branches()
            branch = branch_settings(repo["default_branch"], branches)["read_branch"]
            repo_index = make_repo_index()
            stats = repo_index.stats(github.repo.full_name, branch)
            files = repo_index.indexed_files(github.repo.full_name, branch)
            return jsonify({"stats": stats.__dict__, "files": files})
        except Exception as exc:
            app.logger.exception("Failed to load indexed files")
            return jsonify({"error": str(exc), "files": []}), 500

    @app.route("/issues/<int:issue_number>")
    def issue_detail(issue_number: int):
        try:
            app.logger.info("Loading issue detail issue=%s", issue_number)
            workflow = make_workflow()
            repo = workflow.github.repository()
            branches = workflow.github.list_branches()
            settings = branch_settings(repo["default_branch"], branches)
            context = workflow.issue_context(issue_number)
            plan = workflow.plan_files(issue_number, branch=settings["read_branch"])
            return render_template("issue.html", **context, plan=plan, branches=branches, branch_settings=settings)
        except Exception as exc:
            flash(str(exc), "error")
            return redirect(url_for("dashboard"))

    @app.route("/issues/<int:issue_number>/proposal", methods=["POST"])
    def generate_proposal(issue_number: int):
        selected_files = request.form.getlist("files")
        proposal_mode = request.form.get("proposal_mode", "fast")
        try:
            app.logger.info(
                "Generating proposal issue=%s mode=%s selected_files=%s",
                issue_number,
                proposal_mode,
                len(selected_files),
            )
            workflow = make_workflow()
            settings = posted_branch_settings(workflow.github)
            proposal = workflow.generate_proposal(
                issue_number,
                selected_files or None,
                proposal_mode=proposal_mode,
                read_branch=settings["read_branch"],
                target_branch=settings["target_branch"],
            )
            validation_warnings = validate_proposal_changes(app, proposal.get("changes", []))
            if validation_warnings:
                proposal.setdefault("patch", {})["validation_warnings"] = validation_warnings
            proposal_id = proposal_store().save(proposal)
            app.logger.info("Proposal generated issue=%s proposal_id=%s changes=%s", issue_number, proposal_id, len(proposal.get("changes", [])))
            flash("Codex proposal generated. Review the diffs before creating the PR.", "success")
            return redirect(url_for("review_proposal", proposal_id=proposal_id))
        except CodexTimeout as exc:
            app.logger.warning("Proposal generation timed out issue=%s: %s", issue_number, exc)
            flash("Codex timed out while generating the proposal. Reduce selected files or retry.", "error")
            return redirect(url_for("issue_detail", issue_number=issue_number))
        except CodexTransientError as exc:
            app.logger.warning("Proposal generation hit transient OpenAI error issue=%s: %s", issue_number, exc)
            flash("OpenAI is temporarily unavailable. Please retry in a moment.", "error")
            return redirect(url_for("issue_detail", issue_number=issue_number))
        except Exception as exc:
            app.logger.exception("Proposal generation failed issue=%s", issue_number)
            flash(str(exc), "error")
            return redirect(url_for("issue_detail", issue_number=issue_number))

    @app.route("/issues/<int:issue_number>/aider-run", methods=["POST"])
    def run_aider(issue_number: int):
        selected_files = request.form.getlist("files")
        try:
            token, repo_name = current_settings()
            github = make_github()
            settings = posted_branch_settings(github)
            job = aider_jobs.create(issue_number)
            app.logger.info(
                "Queued Aider run job=%s issue=%s selected_files=%s read_branch=%s target_branch=%s",
                job.id,
                issue_number,
                len(selected_files),
                settings["read_branch"],
                settings["target_branch"],
            )
            worker = threading.Thread(
                target=_run_aider_job,
                args=(
                    app,
                    aider_jobs,
                    job.id,
                    token,
                    repo_name,
                    issue_number,
                    selected_files,
                    settings["read_branch"],
                    settings["target_branch"],
                ),
                daemon=True,
            )
            worker.start()
            return redirect(url_for("aider_job_detail", job_id=job.id))
        except Exception as exc:
            app.logger.exception("Failed to queue Aider run issue=%s", issue_number)
            flash(str(exc), "error")
            return redirect(url_for("issue_detail", issue_number=issue_number))

    @app.route("/aider/jobs/<job_id>")
    def aider_job_detail(job_id: str):
        try:
            job = aider_jobs.snapshot(job_id)
            return render_template("aider_job.html", job=job)
        except Exception as exc:
            flash(str(exc), "error")
            return redirect(url_for("dashboard"))

    @app.route("/aider/jobs/<job_id>.json")
    def aider_job_status(job_id: str):
        try:
            return jsonify(aider_jobs.snapshot(job_id))
        except Exception as exc:
            return jsonify({"state": "error", "error": str(exc), "logs": []}), 404

    @app.route("/issues/<int:issue_number>/agent-run", methods=["POST"])
    def run_agent_loop(issue_number: int):
        selected_files = request.form.getlist("files")
        try:
            app.logger.info(
                "Starting iterative agent run issue=%s selected_files=%s",
                issue_number,
                len(selected_files),
            )
            agent = make_agent_loop()
            settings = posted_branch_settings(agent.workflow.github)
            proposal = agent.run(
                issue_number,
                selected_files or None,
                read_branch=settings["read_branch"],
                target_branch=settings["target_branch"],
            )
            proposal_id = proposal_store().save(proposal)
            app.logger.info(
                "Iterative agent run completed issue=%s proposal_id=%s changes=%s steps=%s",
                issue_number,
                proposal_id,
                len(proposal.get("changes", [])),
                len(proposal.get("patch", {}).get("agent_steps", [])),
            )
            flash("Codex agent run completed. Review the final diff before creating the PR.", "success")
            return redirect(url_for("review_proposal", proposal_id=proposal_id))
        except CodexTimeout as exc:
            app.logger.warning("Agent run timed out issue=%s: %s", issue_number, exc)
            flash("Codex timed out during the agent run. Reduce selected files or retry.", "error")
            return redirect(url_for("issue_detail", issue_number=issue_number))
        except CodexTransientError as exc:
            app.logger.warning("Agent run hit transient OpenAI error issue=%s: %s", issue_number, exc)
            flash("OpenAI is temporarily unavailable. Please retry in a moment.", "error")
            return redirect(url_for("issue_detail", issue_number=issue_number))
        except Exception as exc:
            app.logger.exception("Iterative agent run failed issue=%s", issue_number)
            flash(str(exc), "error")
            return redirect(url_for("issue_detail", issue_number=issue_number))

    @app.route("/proposals/<proposal_id>")
    def review_proposal(proposal_id: str):
        try:
            proposal = attach_diffs(proposal_store().load(proposal_id))
            app.logger.info("Reviewing proposal proposal_id=%s changes=%s", proposal_id, len(proposal.get("changes", [])))
            proposal_target = proposal.get("target_branch") or proposal.get("base_branch") or ""
            try:
                github = make_github()
                repo = github.repository()
                branches = github.list_branches()
                settings = branch_settings(repo["default_branch"], branches)
                proposal_target = proposal_target or settings["target_branch"]
            except Exception as branch_exc:
                app.logger.warning("Could not load branches for proposal review: %s", branch_exc)
                fallback_branch = proposal_target or proposal.get("read_branch") or proposal.get("base_branch") or "main"
                branches = [fallback_branch]
                settings = {"read_branch": proposal.get("read_branch") or fallback_branch, "target_branch": fallback_branch, "default_branch": fallback_branch}
            if proposal_target not in branches:
                proposal_target = settings["target_branch"]
            return render_template("proposal.html", proposal=proposal, branches=branches, branch_settings=settings, proposal_target_branch=proposal_target)
        except Exception as exc:
            app.logger.exception("Proposal review failed proposal_id=%s", proposal_id)
            flash(str(exc), "error")
            return redirect(url_for("dashboard"))

    @app.route("/proposals/<proposal_id>/retry-file", methods=["POST"])
    def retry_proposal_file(proposal_id: str):
        path = request.form.get("path", "").strip()
        if not path:
            flash("Missing file path to retry.", "error")
            return redirect(url_for("review_proposal", proposal_id=proposal_id))

        try:
            store = proposal_store()
            proposal = store.load(proposal_id)
            prior_steps = proposal.get("patch", {}).get("agent_steps", [])
            app.logger.info("Retrying proposal file proposal_id=%s path=%s", proposal_id, path)
            retry_result = make_agent_loop().retry_file(proposal, path, prior_steps=prior_steps)
            _merge_retry_result(proposal, retry_result, path)
            store.update(proposal)
            flash(f"Retried {path} and merged the result into this proposal.", "success")
            return redirect(url_for("review_proposal", proposal_id=proposal_id))
        except Exception as exc:
            app.logger.exception("Retry proposal file failed proposal_id=%s path=%s", proposal_id, path)
            flash(str(exc), "error")
            return redirect(url_for("review_proposal", proposal_id=proposal_id))

    @app.route("/proposals/<proposal_id>/create-pr", methods=["POST"])
    def create_pr_from_proposal(proposal_id: str):
        try:
            if request.form.get("retry_file_intent"):
                flash("Retry request was blocked from creating a PR. Use the Retry this file button again.", "error")
                return redirect(url_for("review_proposal", proposal_id=proposal_id))
            store = proposal_store()
            proposal = store.load(proposal_id)
            app.logger.info("Creating PR from proposal proposal_id=%s", proposal_id)
            for index, change in enumerate(proposal.get("changes", [])):
                edited_content = request.form.get(f"content_{index}")
                if edited_content is not None:
                    change["proposed_content"] = edited_content
            proposal["patch"]["summary"] = request.form.get("summary", proposal["patch"].get("summary", ""))
            proposal["patch"]["test_plan"] = request.form.get("test_plan", proposal["patch"].get("test_plan", ""))
            target_branch = request.form.get("target_branch", proposal.get("target_branch", "")).strip()
            if target_branch:
                branches = make_github().list_branches()
                if target_branch not in branches:
                    raise ValueError(f"Unknown PR target branch: {target_branch}")
                proposal["target_branch"] = target_branch
                session["github_target_branch"] = target_branch
            validation_warnings = validate_proposal_changes(app, proposal.get("changes", []))
            if validation_warnings:
                proposal.setdefault("patch", {})["validation_warnings"] = validation_warnings
            store.update(proposal)

            workflow = make_workflow()
            result = workflow.create_pr_from_proposal(proposal)
            app.logger.info("Created PR proposal_id=%s pr=%s branch=%s", proposal_id, result["pr"].get("html_url"), result["branch"])
            flash(f"Created PR #{result['pr']['number']} on branch {result['branch']}.", "success")
            return redirect(result["pr"]["html_url"])
        except Exception as exc:
            app.logger.exception("Create PR failed proposal_id=%s", proposal_id)
            flash(str(exc), "error")
            return redirect(url_for("review_proposal", proposal_id=proposal_id))

    @app.route("/health")
    def health():
        return {"status": "ok"}

    return app


def _merge_retry_result(proposal: dict, retry_result: dict, retried_path: str) -> None:
    existing_changes = proposal.setdefault("changes", [])
    replacement_by_path = {change["path"]: change for change in retry_result.get("changes", [])}
    merged = []
    seen = set()
    for change in existing_changes:
        path = change.get("path")
        if path in replacement_by_path:
            merged.append(replacement_by_path[path])
            seen.add(path)
        else:
            merged.append(change)
            if path:
                seen.add(path)
    for path, change in replacement_by_path.items():
        if path not in seen:
            merged.append(change)
    proposal["changes"] = merged

    patch = proposal.setdefault("patch", {})
    retry_patch = retry_result.get("patch", {})
    patch["summary"] = retry_patch.get("summary") or patch.get("summary", "")
    patch["test_plan"] = retry_patch.get("test_plan") or patch.get("test_plan", "")
    agent_steps = patch.setdefault("agent_steps", [])
    agent_steps.append(
        {
            "step": len(agent_steps) + 1,
            "action": "retry_file",
            "status": "done",
            "path": retried_path,
            "summary": f"Retried failed file {retried_path}.",
        }
    )
    agent_steps.extend(retry_patch.get("agent_steps", []))

    codex = proposal.setdefault("codex", {})
    codex["agent"] = codex.get("agent") or retry_result.get("codex", {}).get("agent")
    codex["mode"] = "iterative agent with file retry"


def _run_aider_job(
    app: Flask,
    aider_jobs: AiderJobRegistry,
    job_id: str,
    token: str,
    repo_name: str,
    issue_number: int,
    selected_files: list[str],
    read_branch: str,
    target_branch: str,
) -> None:
    with app.app_context():
        def progress(message: str) -> None:
            app.logger.info("Aider job=%s %s", job_id, message)
            aider_jobs.append_log(job_id, message)

        try:
            aider_jobs.update(job_id, state="running", message="Loading GitHub issue.")
            progress("Loading GitHub issue and selected context.")
            github = GitHubClient(token=token, repo=repo_name)
            planner = CodexEngineeringManager(
                app.config["OPENAI_API_KEY"],
                app.config["OPENAI_MODEL"],
                planning_timeout=app.config["OPENAI_PLANNING_TIMEOUT"],
                patch_timeout=app.config["OPENAI_PATCH_TIMEOUT"],
                max_retries=app.config["OPENAI_MAX_RETRIES"],
            )
            workflow = GitHubCTOWorkflow(
                github=github,
                planner=planner,
                max_repo_files=app.config["MAX_REPO_FILES"],
                max_file_bytes=app.config["MAX_FILE_BYTES"],
                default_selected_files=app.config["DEFAULT_SELECTED_FILES"],
                max_selected_files=app.config["MAX_SELECTED_FILES"],
                max_context_chars_per_file=app.config["MAX_CONTEXT_CHARS_PER_FILE"],
                max_parallel_fetches=app.config["MAX_PARALLEL_FETCHES"],
                enable_file_summaries=app.config["ENABLE_FILE_SUMMARIES"],
                repo_index=RepositoryIndex(
                    app.instance_path + "/repo_index.sqlite3",
                    OpenAIEmbedder(app.config["OPENAI_API_KEY"], app.config["OPENAI_EMBEDDING_MODEL"]),
                    file_summarizer=OpenAIFileSummarizer(
                        app.config["OPENAI_API_KEY"],
                        app.config["FILE_METADATA_MODEL"],
                        timeout=app.config["FILE_METADATA_TIMEOUT"],
                        enabled=app.config["ENABLE_AI_FILE_METADATA"],
                    ),
                ),
            )
            context = workflow.issue_context(issue_number)
            issue = context["issue"]
            comments = context["comments"]
            triage = context["triage"]
            if not selected_files:
                progress("No files selected; asking planner for file context.")
                selected_files = workflow.plan_files(issue_number, branch=read_branch)["files"]
            backend = AiderBackend(
                repo_root=app.root_path + "/..",
                workspace_root=app.instance_path + "/aider_runs",
                config=AiderConfig(
                    command=app.config["AIDER_COMMAND"],
                    model=app.config["AIDER_MODEL"],
                    timeout=app.config["AIDER_TIMEOUT"],
                    test_command=app.config["AIDER_TEST_COMMAND"],
                    keep_runs=app.config["AIDER_KEEP_RUNS"],
                ),
            )
            reviewer = PatchReviewAgent(
                app.config["OPENAI_API_KEY"],
                app.config["OPENAI_MODEL"],
                timeout=app.config["AIDER_REVIEW_TIMEOUT"],
                max_retries=app.config["OPENAI_MAX_RETRIES"],
            )
            max_attempts = max(1, app.config["AIDER_REVIEW_MAX_ATTEMPTS"])
            reviewer_feedback = ""
            proposal = None
            last_failure = ""
            for attempt in range(1, max_attempts + 1):
                if attempt > 1:
                    progress(f"Retrying Aider with review feedback (attempt {attempt}/{max_attempts}).")
                result = backend.run_issue(
                    issue=issue,
                    comments=comments,
                    selected_files=selected_files,
                    openai_api_key=app.config["OPENAI_API_KEY"],
                    github_token=token,
                    repository=repo_name,
                    branch=read_branch,
                    reviewer_feedback=reviewer_feedback,
                    attempt=attempt,
                    progress=progress,
                )
                proposal = _proposal_from_aider_result(workflow, issue, triage, result, read_branch, target_branch)
                progress("Validating generated changes.")
                try:
                    validation_warnings = validate_proposal_changes(app, proposal.get("changes", []))
                except ProposalValidationError as exc:
                    last_failure = f"Deterministic validation failed:\n{exc}"
                    progress(last_failure)
                    reviewer_feedback = _retry_feedback_from_validation(last_failure)
                    if attempt >= max_attempts:
                        raise
                    continue
                if validation_warnings:
                    proposal.setdefault("patch", {})["validation_warnings"] = validation_warnings

                progress("Reviewing generated changes against the issue.")
                review = reviewer.review(issue, proposal.get("changes", []))
                proposal.setdefault("patch", {})["reviewer"] = review
                if (review.get("verdict") or "").lower() == "pass":
                    progress("Reviewer agent passed the generated changes.")
                    break
                last_failure = _review_failure_text(review)
                progress(last_failure)
                reviewer_feedback = review.get("retry_prompt") or last_failure
                if attempt >= max_attempts:
                    raise AiderRunError(last_failure)

            if proposal is None:
                raise AiderRunError(last_failure or "Aider review loop did not produce a proposal.")
            proposal_id = ProposalStore(app.instance_path + "/proposals").save(proposal)
            progress(f"Aider proposal ready: {proposal_id}.")
            aider_jobs.update(
                job_id,
                state="complete",
                proposal_id=proposal_id,
                message="Aider proposal is ready for review.",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
        except (AiderRunError, ProposalValidationError, Exception) as exc:
            app.logger.exception("Aider job failed job=%s issue=%s", job_id, issue_number)
            aider_jobs.append_log(job_id, f"Error: {exc}")
            aider_jobs.update(
                job_id,
                state="error",
                error=str(exc),
                message="Aider run failed.",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )


def _proposal_from_aider_result(
    workflow: GitHubCTOWorkflow,
    issue: dict,
    triage,
    result: dict,
    read_branch: str | None = None,
    target_branch: str | None = None,
) -> dict:
    read_branch = read_branch or workflow.github.default_branch()
    target_branch = target_branch or read_branch
    changes = []
    for change in result.get("changes", []):
        path = change["path"]
        try:
            original = workflow.github.get_file(path, ref=read_branch)
            original_content = original["content"]
            sha = original["sha"]
            status = "modified"
        except Exception:
            original_content = ""
            sha = None
            status = "new"
        changes.append(
            {
                "path": path,
                "status": status,
                "sha": sha,
                "original_content": original_content,
                "proposed_content": change["proposed_content"],
                "unified_diff": change.get("unified_diff", ""),
            }
        )

    return {
        "issue": {"number": issue.get("number"), "title": issue.get("title"), "html_url": issue.get("html_url")},
        "triage": {
            "severity": triage.severity,
            "score": triage.score,
            "rationale": triage.rationale,
            "recommended_action": triage.recommended_action,
        },
        "patch": {
            "summary": "Aider generated a reviewable code change for this issue.",
            "test_plan": "Review the diff and run the configured test suite before merging.",
            "aider_output": result.get("output", ""),
            "aider_run_id": result.get("run_id", ""),
            "aider_workspace": result.get("workspace", ""),
        },
        "base_branch": read_branch,
        "read_branch": read_branch,
        "target_branch": target_branch,
        "changes": changes,
        "codex": {
            "agent": "Aider CLI Backend",
            "mode": "Flask orchestrated repo-editing CLI",
            "model": "aider",
            "timeline": codex_timeline_for_aider(len(changes), result.get("run_id", "")),
        },
    }


def _retry_feedback_from_validation(message: str) -> str:
    return (
        "Your previous patch failed deterministic validation. Revise the patch to fix these issues without "
        "adding unrelated changes:\n"
        f"{message}"
    )


def _review_failure_text(review: dict) -> str:
    findings = review.get("findings") or []
    lines = ["Reviewer agent rejected the patch."]
    for finding in findings[:6]:
        if isinstance(finding, dict):
            lines.append(
                "- "
                f"{finding.get('severity', 'issue')} "
                f"{finding.get('file', '')}: "
                f"{finding.get('issue', '')} "
                f"Suggestion: {finding.get('suggestion', '')}".strip()
            )
    if review.get("retry_prompt"):
        lines.append(f"Retry guidance: {review.get('retry_prompt')}")
    return "\n".join(lines)


def codex_timeline_for_aider(changed_files: int, run_id: str) -> list[dict[str, str]]:
    return [
        {"key": "intake", "title": "Read GitHub issue", "detail": "Loaded issue and comments from GitHub.", "status": "done"},
        {"key": "context", "title": "Select code context", "detail": "Used selected files as Aider chat context.", "status": "done"},
        {"key": "edit", "title": "Run Aider", "detail": f"Aider edited files in isolated workspace {run_id}.", "status": "done"},
        {"key": "review", "title": "Human checkpoint", "detail": f"{changed_files} changed file(s) ready for review.", "status": "active"},
    ]


def _run_index_rebuild(app: Flask, index_jobs: IndexJobRegistry, token: str, repo_name: str, branch: str) -> None:
    with app.app_context():
        try:
            github = GitHubClient(token=token, repo=repo_name)
            embedder = OpenAIEmbedder(app.config["OPENAI_API_KEY"], app.config["OPENAI_EMBEDDING_MODEL"])
            summarizer = OpenAIFileSummarizer(
                app.config["OPENAI_API_KEY"],
                app.config["FILE_METADATA_MODEL"],
                timeout=app.config["FILE_METADATA_TIMEOUT"],
                enabled=app.config["ENABLE_AI_FILE_METADATA"],
            )
            repo_index = RepositoryIndex(app.instance_path + "/repo_index.sqlite3", embedder, file_summarizer=summarizer)

            def progress(**kwargs):
                index_jobs.update(**kwargs)
                if "message" in kwargs:
                    app.logger.info("Index progress: %s", kwargs["message"])

            stats = repo_index.rebuild(
                github,
                max_files=app.config["MAX_REPO_FILES"],
                max_file_bytes=app.config["MAX_FILE_BYTES"],
                branch=branch,
                progress=progress,
            )
            index_jobs.finish(f"Index complete: {stats.files} files and {stats.chunks} chunks.")
        except Exception as exc:
            app.logger.exception("Index rebuild failed")
            index_jobs.fail(str(exc))


def setup_logging(app: Flask) -> None:
    log_dir = app.instance_path
    try:
        import os

        os.makedirs(log_dir, exist_ok=True)
    except OSError:
        pass

    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    file_handler = RotatingFileHandler(f"{log_dir}/github_cto.log", maxBytes=1_000_000, backupCount=3)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.INFO)

    app.logger.setLevel(logging.INFO)
    app.logger.handlers.clear()
    app.logger.addHandler(file_handler)
    app.logger.addHandler(stream_handler)

    package_logger = logging.getLogger("github_cto")
    package_logger.setLevel(logging.INFO)
    package_logger.handlers.clear()
    package_logger.addHandler(file_handler)
    package_logger.addHandler(stream_handler)
    package_logger.propagate = False
