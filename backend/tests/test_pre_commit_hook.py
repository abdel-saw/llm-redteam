"""Tests d'intégration du hook .githooks/pre-commit via subprocess.

On crée un mini repo git temporaire, on y branche le hook, et on
vérifie son comportement sur trois scénarios :
1. Vraie clé non-whitelistée → le commit est refusé.
2. Même clé avec marqueur FAKER sur la même ligne → commit passe.
3. Clé enfouie dans un fichier marqué binaire par git → le hook skip.

Pour ne pas écrire de patterns de vraies clés en littéral dans ce
fichier (qui serait alors flag par test_no_real_keys_in_codebase.py),
les valeurs sont assemblées dynamiquement par concaténation.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK_SOURCE = REPO_ROOT / ".githooks" / "pre-commit"


def _bash_available() -> bool:
    return shutil.which("bash") is not None


pytestmark = pytest.mark.skipif(
    not _bash_available(),
    reason="bash is required to run the pre-commit hook (Git for Windows ships one).",
)


def _fake_groq_key() -> str:
    # Build "gsk_" + 50 alnum chars by concatenation so this very file
    # contains no literal long gsk_-string that would itself trip the
    # scanner.
    return "gsk_" + ("A" * 50)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    hooks_dir = repo / ".githooks"
    hooks_dir.mkdir()
    shutil.copy(HOOK_SOURCE, hooks_dir / "pre-commit")
    (hooks_dir / "pre-commit").chmod(0o755)

    def _run(*cmd: str) -> None:
        subprocess.run(cmd, cwd=repo, check=True,
                       capture_output=True, text=True)

    _run("git", "init", "-q", "-b", "main")
    _run("git", "config", "core.hooksPath", ".githooks")
    _run("git", "config", "user.email", "test@example.com")
    _run("git", "config", "user.name", "Test User")
    _run("git", "config", "commit.gpgsign", "false")
    return repo


def _commit(repo: Path, message: str) -> subprocess.CompletedProcess:
    """Tente un commit avec capture d'output. Ne lève PAS sur exit≠0
    pour qu'on puisse asserter sur le code de retour."""
    return subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


class TestPreCommitHook:
    def test_pre_commit_hook_detects_real_groq_key(self, git_repo: Path):
        secret_path = git_repo / "leak.py"
        secret_path.write_text(
            f'PRODUCTION_KEY = "{_fake_groq_key()}"\n',
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "add", "leak.py"], cwd=git_repo, check=True
        )

        result = _commit(git_repo, "should be blocked")

        assert result.returncode != 0, (
            f"hook should have blocked the commit, got rc={result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        combined = (result.stdout + result.stderr).lower()
        assert "potential secret detected" in combined
        assert "leak.py" in combined

    def test_pre_commit_hook_allows_whitelisted_fake_key(self, git_repo: Path):
        # Same pattern, but the line carries a FAKER marker → allowed.
        fixture_path = git_repo / "fixture.py"
        fixture_path.write_text(
            f'FAKER_KEY = "{_fake_groq_key()}"\n',
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "add", "fixture.py"], cwd=git_repo, check=True
        )

        result = _commit(git_repo, "fixture with FAKER marker")

        assert result.returncode == 0, (
            f"hook should have let this commit through, got rc={result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_pre_commit_hook_skips_binary_files(self, git_repo: Path):
        # Embed the fake key inside a buffer that git will classify as
        # binary (presence of NUL bytes is the standard trigger).
        binary_path = git_repo / "blob.bin"
        payload = (
            b"\x00\x01"
            + _fake_groq_key().encode("ascii")
            + b"\x00trailing\x00"
        )
        binary_path.write_bytes(payload)
        subprocess.run(
            ["git", "add", "blob.bin"], cwd=git_repo, check=True
        )

        result = _commit(git_repo, "binary blob")

        # Binary files are not scanned → commit should succeed.
        assert result.returncode == 0, (
            f"hook should have skipped the binary file, got rc={result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
