"""Ceinture en plus de la bretelle : scanne tout le code source tracké
par git à la recherche de chaînes ressemblant à de vraies clés d'API.

Le pre-commit hook (`.githooks/pre-commit`) est la première ligne de
défense au moment du commit. Ce test, lui, tourne en CI et au local
chaque fois qu'on lance pytest — il rattrape les secrets qui auraient
été commités via `git commit --no-verify`, ou avant que le hook ne
soit activé.

Whitelist : un secret-like est ignoré si la ligne où il apparaît
contient l'un des marqueurs FAKER, REDACTED, EXAMPLE, DUMMY,
PLACEHOLDER, xxxxx, TEST_, test_, ou fake (case-insensitive). Pour
les fixtures de tests qui doivent ressembler à de vraies clés, c'est
le bon réflexe.

Ce fichier lui-même contient des patterns d'exemple : ils sont
intentionnellement assortis du marqueur EXAMPLE / FAKER / TEST_, donc
le scan ne les détecte pas.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Patterns to flag. Anchor on the prefix specific to each vendor so we
# don't false-positive on arbitrary base64-ish strings.
SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"gsk_[A-Za-z0-9]{30,}"),
    re.compile(r"sk-[A-Za-z0-9]{30,}"),
    re.compile(r"sk-or-v1-[A-Za-z0-9]{20,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"Bearer [A-Za-z0-9._-]{40,}"),
]

# Case-insensitive substring match on the offending LINE (not just the
# matched span). Same whitelist as the pre-commit hook.
WHITELIST_RE = re.compile(
    r"FAKER|REDACTED|EXAMPLE|DUMMY|PLACEHOLDER|xxxxx|TEST_|test_|fake",
    re.IGNORECASE,
)

# Files we never want to scan (binary or vendored).
SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
    ".pdf", ".zip", ".gz", ".tar", ".woff", ".woff2",
    ".db", ".sqlite", ".sqlite3",
}
# Files we explicitly allow to contain "secret-like" tokens for
# documentation purposes — these typically describe the patterns but
# never carry a real key. We still scan them, but a single placeholder
# in code blocks is fine because each occurrence carries a whitelist
# token by convention.
DOC_PATHS = {
    "CONTRIBUTING.md",
    ".githooks/pre-commit",
    ".githooks/pre-commit.ps1",
    "backend/tests/test_no_real_keys_in_codebase.py",
    "backend/tests/test_pre_commit_hook.py",
    "backend/app/security/redaction.py",
}


def _tracked_files() -> list[Path]:
    """Liste des fichiers tracked par git (ignore env/, .git/, etc.)."""
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [
        REPO_ROOT / line
        for line in result.stdout.splitlines()
        if line.strip()
    ]


def _scan(path: Path) -> list[tuple[int, str, str]]:
    """Retourne la liste des (line_number, pattern, matched_value) sur
    les violations détectées (whitelist déjà appliquée)."""
    findings: list[tuple[int, str, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return findings
    for lineno, line in enumerate(text.splitlines(), 1):
        if WHITELIST_RE.search(line):
            continue
        for pat in SECRET_PATTERNS:
            m = pat.search(line)
            if m:
                findings.append((lineno, pat.pattern, m.group(0)))
    return findings


def test_no_real_keys_anywhere_in_repo():
    """Aucun fichier tracked ne doit contenir une chaîne qui ressemble
    à une vraie clé non-whitelistée."""
    violations: list[tuple[Path, int, str, str]] = []
    for path in _tracked_files():
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        if not path.exists() or not path.is_file():
            continue
        # Files in DOC_PATHS may contain pattern examples for the docs
        # themselves — we still scan them, but the convention is that
        # every example carries a whitelist marker.
        rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        _ = rel in DOC_PATHS  # noted; not used for skip — kept for review
        for lineno, pattern, matched in _scan(path):
            violations.append((path, lineno, pattern, matched))

    if violations:
        details = "\n".join(
            f"  {p.relative_to(REPO_ROOT)}:{ln} "
            f"matched /{pat}/ -> {value[:6]}...{value[-4:]}"
            for p, ln, pat, value in violations
        )
        pytest.fail(
            "Real-looking API keys detected in the codebase:\n"
            f"{details}\n"
            "Either remove the value or add a whitelist marker on the "
            "same line (FAKER, REDACTED, EXAMPLE, DUMMY, PLACEHOLDER, "
            "TEST_, or 'fake')."
        )


# --- Sanity tests on the scanner itself -----------------------------------


class TestScannerLogic:
    # The "real-shape" gsk_ value is built dynamically so this very
    # file doesn't contain a literal long secret-shaped string. The
    # scanner reads the *contents of the file written to tmp_path*,
    # not this source file, so the test still exercises a true match.
    _LONG_ALNUM = "AbCdEf0123456789" * 3 + "ZZ"

    def test_pattern_matches_real_groq_shape(self, tmp_path):
        # A long gsk_-prefixed token without any whitelist hint must
        # trigger a finding. (FAKER tag in the variable name is not
        # enough if it's not on the same line as the value.)
        body = 'leaked = "gsk_' + self._LONG_ALNUM + '"\n'
        f = tmp_path / "leak.py"
        f.write_text(body)
        findings = _scan(f)
        assert findings, "scanner should have detected the gsk_ pattern"

    def test_whitelist_token_on_same_line_suppresses_match(self, tmp_path):
        # Le marqueur FAKER est sur la même ligne → pas de violation.
        body = 'FAKER_KEY = "gsk_' + self._LONG_ALNUM + '"\n'
        f = tmp_path / "fixture.py"
        f.write_text(body)
        assert _scan(f) == []

    def test_skips_unicode_decode_errors(self, tmp_path):
        # Un fichier binaire ne doit pas planter le scanner.
        f = tmp_path / "binary.bin"
        f.write_bytes(b"\xff\xfe\x00garbage\xc3\x28invalid")
        assert _scan(f) == []
