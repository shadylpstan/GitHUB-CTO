from __future__ import annotations

import logging
import threading
from logging.handlers import RotatingFileHandler

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for

from .agent_loop import AgentLoopConfig, IterativeAgentLoop
from .ai import CodexEngineeringManager, CodexTimeout, CodexTransientError
from .config import Config
from .github_client import GitHubClient, GitHubError
from .index_jobs import IndexJobRegistry
from .proposals import ProposalStore, attach_diffs
from .repo_index import OpenAIEmbedder, RepositoryIndex
from .triage import triage_issue
from .workflow import GitHubCTOWorkflow


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    setup_logging(app)
    index_jobs = IndexJobRegistry()

    def current_settings() -> tuple[str, str]:
        token = session.get("github_token") or app.config["GITHUB_TOKEN"]
        repo = session.get("github_repo") or app.config["GITHUB_REPOSITORY"]
        return token, repo

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
        return RepositoryIndex(app.instance_path + "/repo_index.sqlite3", embedder)

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
                max_context_chars_per_file=min(app.config["MAX_CONTEXT_CHARS_PER_FILE"], 6000),
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
        flash("Browser override cleared. Using .env settings again.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/dashboard")
    def dashboard():
        try:
            github = make_github()
            repo = github.repository()
            user = github.current_user()
            app.logger.info("Loading dashboard for repo=%s user=%s", github.repo.full_name, user.get("login"))
            issues = github.list_issues(limit=30)
            repo_index = make_repo_index()
            index_stats = repo_index.stats(github.repo.full_name, repo["default_branch"])
            indexed_files = repo_index.indexed_files(github.repo.full_name, repo["default_branch"])
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
            branch = repo["default_branch"]
            index_jobs.start(github.repo.full_name, branch)
            app.logger.info("Queued index rebuild for %s on %s", github.repo.full_name, branch)

            worker = threading.Thread(
                target=_run_index_rebuild,
                args=(app, index_jobs, token, repo_name),
                daemon=True,
            )
            worker.start()
            flash("Repository index rebuild started. Progress will update below.", "success")
        except Exception as exc:
            app.logger.exception("Failed to start index rebuild")
            index_jobs.fail(str(exc))
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
            repo_index = make_repo_index()
            stats = repo_index.stats(github.repo.full_name, repo["default_branch"])
            files = repo_index.indexed_files(github.repo.full_name, repo["default_branch"])
            return jsonify({"stats": stats.__dict__, "files": files})
        except Exception as exc:
            app.logger.exception("Failed to load indexed files")
            return jsonify({"error": str(exc), "files": []}), 500

    @app.route("/issues/<int:issue_number>")
    def issue_detail(issue_number: int):
        try:
            app.logger.info("Loading issue detail issue=%s", issue_number)
            workflow = make_workflow()
            context = workflow.issue_context(issue_number)
            plan = workflow.plan_files(issue_number)
            return render_template("issue.html", **context, plan=plan)
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
            proposal = workflow.generate_proposal(issue_number, selected_files or None, proposal_mode=proposal_mode)
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
            proposal = agent.run(issue_number, selected_files or None)
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
            return render_template("proposal.html", proposal=proposal)
        except Exception as exc:
            app.logger.exception("Proposal review failed proposal_id=%s", proposal_id)
            flash(str(exc), "error")
            return redirect(url_for("dashboard"))

    @app.route("/proposals/<proposal_id>/create-pr", methods=["POST"])
    def create_pr_from_proposal(proposal_id: str):
        try:
            store = proposal_store()
            proposal = store.load(proposal_id)
            app.logger.info("Creating PR from proposal proposal_id=%s", proposal_id)
            for index, change in enumerate(proposal.get("changes", [])):
                edited_content = request.form.get(f"content_{index}")
                if edited_content is not None:
                    change["proposed_content"] = edited_content
            proposal["patch"]["summary"] = request.form.get("summary", proposal["patch"].get("summary", ""))
            proposal["patch"]["test_plan"] = request.form.get("test_plan", proposal["patch"].get("test_plan", ""))
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


def _run_index_rebuild(app: Flask, index_jobs: IndexJobRegistry, token: str, repo_name: str) -> None:
    with app.app_context():
        try:
            github = GitHubClient(token=token, repo=repo_name)
            embedder = OpenAIEmbedder(app.config["OPENAI_API_KEY"], app.config["OPENAI_EMBEDDING_MODEL"])
            repo_index = RepositoryIndex(app.instance_path + "/repo_index.sqlite3", embedder)

            def progress(**kwargs):
                index_jobs.update(**kwargs)
                if "message" in kwargs:
                    app.logger.info("Index progress: %s", kwargs["message"])

            stats = repo_index.rebuild(
                github,
                max_files=app.config["MAX_REPO_FILES"],
                max_file_bytes=app.config["MAX_FILE_BYTES"],
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
    logging.getLogger("github_cto").setLevel(logging.INFO)
