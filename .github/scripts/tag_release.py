"""Create an immutable SDK tag and safely retry its publication dispatch."""

import json
import os
import subprocess
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import urlopen

import tomllib

REPOSITORY = "ofspectrum/python-sdk"


def command(root: Path, *args: str) -> str:
    return subprocess.run(
        args, cwd=root, check=True, capture_output=True, text=True,
    ).stdout.strip()


def already_published(version: str) -> bool:
    url = f"https://pypi.org/pypi/ofspectrum/{quote(version, safe='')}/json"
    try:
        with urlopen(url, timeout=15) as response:
            metadata = json.load(response)
    except HTTPError as error:
        if error.code == 404:
            return False
        raise
    if metadata.get("info", {}).get("version") != version:
        raise ValueError("PyPI release metadata does not match the SDK version")
    return True


def main(root: Path = Path(".")) -> None:
    if os.environ.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise ValueError("SDK release tagging must run in the public SDK repository")
    root = root.resolve()
    if Path(command(root, "git", "rev-parse", "--show-toplevel")).resolve() != root:
        raise ValueError("Run SDK release tagging from the SDK repository root")
    version = str(tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"])
    tag = f"v{version}"
    command(root, "git", "check-ref-format", f"refs/tags/{tag}")
    command(root, "git", "fetch", "origin", "--tags")
    refs = command(root, "git", "tag", "--list", tag).splitlines()
    if tag not in refs:
        command(root, "git", "-c", "user.name=github-actions[bot]", "-c",
                "user.email=github-actions[bot]@users.noreply.github.com",
                "tag", "-a", tag, "-m", f"Release {tag}")
    else:
        print(f"Reusing immutable release tag {tag}")

    tag_project = tomllib.loads(command(root, "git", "show", f"{tag}:pyproject.toml"))
    if tag_project["project"]["version"] != version:
        raise ValueError("Existing release tag has a different package version")
    if command(root, "git", "diff", f"{tag}^{{commit}}", "HEAD", "--", "pyproject.toml", "ofspectrum"):
        raise ValueError("SDK runtime changed after tagging; use a new release version")
    # An earlier tag push can fail too. Retrying the exact ref is idempotent;
    # never force-update an existing remote tag.
    command(root, "git", "push", "origin", f"refs/tags/{tag}")
    if already_published(version):
        print(f"SDK {version} is already on PyPI; no publication dispatched")
        return

    commit = command(root, "git", "rev-parse", f"{tag}^{{commit}}")
    runs = json.loads(command(
        root, "gh", "run", "list", "--repo", REPOSITORY,
        "--workflow", "publish.yml", "--branch", tag, "--limit", "100",
        "--json", "headSha,headBranch,status",
    ))
    if not isinstance(runs, list) or any(
        not isinstance(run, dict) or not all(run.get(key) for key in ("headSha", "headBranch", "status"))
        for run in runs
    ):
        raise ValueError("Publication run evidence is unavailable")
    if any(run["headSha"] == commit and run["headBranch"] == tag and run["status"] != "completed" for run in runs):
        print(f"Publication for {tag} is already active; no duplicate dispatched")
        return

    # A GITHUB_TOKEN tag push does not trigger tag-push workflows. Dispatch
    # explicitly, including when retrying after an earlier dispatch failure.
    command(root, "gh", "workflow", "run", "publish.yml", "--repo", REPOSITORY, "--ref", tag)
    print(f"Publication dispatched for {tag}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Never print token-bearing environment variables or provider bodies.
        raise SystemExit(f"SDK release preparation failed ({type(error).__name__}); verify the release tag and retry.") from None
