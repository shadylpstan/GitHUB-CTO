import os

from dotenv import load_dotenv


load_dotenv()


class Config:
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "github-cto-dev-secret")
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
    GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    FILE_METADATA_MODEL = os.getenv("FILE_METADATA_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
    ENABLE_AI_FILE_METADATA = os.getenv("ENABLE_AI_FILE_METADATA", "true").lower() == "true"
    FILE_METADATA_TIMEOUT = int(os.getenv("FILE_METADATA_TIMEOUT", "45"))
    OPENAI_PLANNING_TIMEOUT = int(os.getenv("OPENAI_PLANNING_TIMEOUT", "60"))
    OPENAI_PATCH_TIMEOUT = int(os.getenv("OPENAI_PATCH_TIMEOUT", "180"))
    OPENAI_MAX_RETRIES = int(os.getenv("OPENAI_MAX_RETRIES", "2"))
    DEFAULT_SELECTED_FILES = int(os.getenv("DEFAULT_SELECTED_FILES", "5"))
    MAX_SELECTED_FILES = int(os.getenv("MAX_SELECTED_FILES", "8"))
    MAX_CONTEXT_CHARS_PER_FILE = int(os.getenv("MAX_CONTEXT_CHARS_PER_FILE", "12000"))
    MAX_PARALLEL_FETCHES = int(os.getenv("MAX_PARALLEL_FETCHES", "6"))
    ENABLE_FILE_SUMMARIES = os.getenv("ENABLE_FILE_SUMMARIES", "true").lower() == "true"
    MAX_REPO_FILES = int(os.getenv("MAX_REPO_FILES", "350"))
    MAX_FILE_BYTES = int(os.getenv("MAX_FILE_BYTES", "20000"))
    AGENT_MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "4"))
    AGENT_TEST_COMMAND = os.getenv("AGENT_TEST_COMMAND", "")
    AGENT_TEST_TIMEOUT = int(os.getenv("AGENT_TEST_TIMEOUT", "90"))
    AGENT_OPENAI_TIMEOUT = int(os.getenv("AGENT_OPENAI_TIMEOUT", "60"))
    AGENT_OPENAI_MAX_RETRIES = int(os.getenv("AGENT_OPENAI_MAX_RETRIES", "0"))
    AIDER_COMMAND = os.getenv("AIDER_COMMAND", "aider")
    AIDER_MODEL = os.getenv("AIDER_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
    AIDER_TIMEOUT = int(os.getenv("AIDER_TIMEOUT", "600"))
    AIDER_TEST_COMMAND = os.getenv("AIDER_TEST_COMMAND", "")
    AIDER_KEEP_RUNS = int(os.getenv("AIDER_KEEP_RUNS", "5"))
    AIDER_REVIEW_MAX_ATTEMPTS = int(os.getenv("AIDER_REVIEW_MAX_ATTEMPTS", "2"))
    AIDER_REVIEW_TIMEOUT = int(os.getenv("AIDER_REVIEW_TIMEOUT", "60"))
    AGENT_OPENAI_MAX_RETRIES = int(os.getenv("AGENT_OPENAI_MAX_RETRIES", "0"))
