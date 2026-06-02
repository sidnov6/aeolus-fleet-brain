"""Deploy AEOLUS (full stack) to a Hugging Face Docker Space.

Usage:  HF_TOKEN=hf_xxx python deploy/deploy_hf.py [space_name]

Creates/updates a Docker Space, uploads the repo (excluding heavy/secret files),
sets GROQ_API_KEY as a Space secret, and triggers the build. HF builds the
Dockerfile and serves the API + dashboard from one URL.
"""
import os
import sys
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parent.parent
SPACE_NAME = sys.argv[1] if len(sys.argv) > 1 else "aeolus-fleet-brain"

IGNORE = [
    ".venv/*", "**/.venv/*", "**/node_modules/*", "**/dist/*", ".env",
    ".git/*", "**/.vercel/*", "**/__pycache__/*", "*.pyc",
    "data/bronze/*", "data/silver/*", "data/gold/*", "data/chroma/*",
    "data/audit/*", "data/artifacts/*", "data/synthetic/*",
    "*.zip", "data/raw/*.zip", "data/raw/_peek/*",
    "README.md", "deploy/*", "LINKEDIN_POST.md",
]


def read_env(key, default=None):
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get(key, default)


def main():
    token = os.environ.get("HF_TOKEN") or read_env("HF_TOKEN")
    if not token:
        sys.exit("Set HF_TOKEN (a Hugging Face *write* token).")
    api = HfApi(token=token)
    user = api.whoami()["name"]
    repo_id = f"{user}/{SPACE_NAME}"
    print(f"Deploying to Space: {repo_id}")

    api.create_repo(repo_id, repo_type="space", space_sdk="docker", exist_ok=True)

    # Space README (with the docker SDK frontmatter) must be README.md at root
    api.upload_file(path_or_fileobj=str(ROOT / "deploy" / "hf-space-README.md"),
                    path_in_repo="README.md", repo_id=repo_id, repo_type="space")

    api.upload_folder(folder_path=str(ROOT), repo_id=repo_id, repo_type="space",
                      ignore_patterns=IGNORE,
                      commit_message="Deploy AEOLUS full stack (API + dashboard)")

    groq = read_env("GROQ_API_KEY")
    model = read_env("AEOLUS_LLM_MODEL", "groq/llama-3.3-70b-versatile")
    if groq:
        api.add_space_secret(repo_id, "GROQ_API_KEY", groq)
        api.add_space_variable(repo_id, "AEOLUS_LLM_MODEL", model)
        print("  set GROQ_API_KEY secret + AEOLUS_LLM_MODEL")

    app_url = f"https://{user}-{SPACE_NAME}.hf.space".lower()
    print(f"\nSpace:  https://huggingface.co/spaces/{repo_id}")
    print(f"App:    {app_url}")
    print("Building now (Dockerfile) — first build takes a few minutes.")


if __name__ == "__main__":
    main()
