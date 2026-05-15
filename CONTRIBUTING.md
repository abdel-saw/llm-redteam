# Contributing to Red-Agent-S

Thanks for considering a contribution. This project is built as a Master's
final-year project (PFE) and is meant to stay small and focused — pull
requests that expand scope are welcome but please open an issue first
to discuss.

## Setup

```bash
git clone https://github.com/abdel-saw/llm-redteam.git
cd llm-redteam

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env       # fill in GROQ_API_KEY

# Activate the pre-commit hook (one-time, after each clone)
git config core.hooksPath .githooks
```

Once `core.hooksPath` is set, every `git commit` runs
`.githooks/pre-commit` which scans the staged diff for accidentally
committed API keys (see *Security* below).

## Running tests

```bash
pytest -v --cache-clear
```

Expected: 113 tests pass. Subsets:

```bash
pytest backend/tests/test_redaction.py -v        # redaction + log filter
pytest backend/tests/test_safety_classifier.py   # safety judge factory
pytest backend/tests/test_no_real_keys_in_codebase.py  # secret-leak guard
```

The `test_pre_commit_hook` tests are auto-skipped on environments without
`bash` on PATH. On Windows, Git for Windows installs bash by default.

## Security

This is the most important section of this file.

### Never paste a real API key in a test or fixture

Not even temporarily, not even "I'll remove it before the commit". The
git history has long memory; once a real key reaches `origin/main`, it
must be considered **compromised and rotated immediately**.

A real incident triggered this whole guard: a real Groq key ended up in
a test fixture (an LLM assistant generated a plausible-looking value,
which happened to be the actual `.env` value), reached `origin`, and
had to be scrubbed via `git filter-repo` + key rotation. The pre-commit
hook is the lesson learned.

### How to write a fixture that looks like a key

If you absolutely need a string that *looks* like a real key in a test,
ensure the same line contains one of these whitelist tokens
(case-insensitive substring match):

`FAKER`, `REDACTED`, `EXAMPLE`, `DUMMY`, `PLACEHOLDER`, `xxxxx`,
`TEST_`, `test_`, `fake`

```python
# ✅ Good — same line, no real value:
FAKER_KEY = "gsk_FAKERkey1234567890abcdefghijklmnop"
api_call(headers={"Authorization": "Bearer gsk_FAKERtoken_REDACTED_..."})

# ❌ Bad — looks just like a real Groq key:
PRODUCTION_KEY = "gsk_aZ19fKQq3vH7..."
```

Both the pre-commit hook (`.githooks/pre-commit`) and the pytest test
(`backend/tests/test_no_real_keys_in_codebase.py`) enforce this.

### If Claude Code (or any LLM assistant) generates a test for you

LLM assistants can hallucinate plausible-looking key values. Worse:
they sometimes paste a value that *was* in your context (e.g. your
`.env`). Before committing AI-generated test code, do:

```bash
grep -E "gsk_|sk-or-v1-|sk-ant-|Bearer " <generated_file>
```

and confirm by eyeball that no value looks identical to anything in
your real `.env`. If in doubt, regenerate the value with a clear FAKER
prefix.

### Bypassing the hook

`git commit --no-verify` skips the pre-commit hook. **Do not use this
casually.** If you have a legitimate reason (e.g. the regex flagged a
non-secret on a borderline match), the pytest test will still catch a
real key — but only after you push and run CI. Better to fix the
fixture to include a whitelist token.

### What to do if a real key did slip through

1. **Rotate immediately** (Groq / OpenRouter / etc. console → revoke
   the key, issue a new one).
2. Scrub the commit history with `git filter-repo` (preferred) or
   `git filter-branch`.
3. Force-push to all remotes (`git push --force-with-lease`).
4. Notify any collaborator who pulled the leaky commit.
5. Add a journal entry under `docs/journal.md`.

## Code style

- Python: stay close to PEP 8. No formatter is enforced (the project is
  small enough to read by eye) but consistent with the existing style.
- Docstrings: brief module-level docstrings explaining intent; avoid
  redundant `"""Return X."""` style on obvious helpers.
- Comments: explain *why*, not *what*. The code shows what.

## Commit messages

Conventional-Commits style is preferred:

```
type(scope): short imperative summary

Optional body with paragraph-form context — what changed and why,
not how. Wrap at ~72 cols.

Optional trailer.
```

Types in use: `feat`, `fix`, `refactor`, `docs`, `ci`, `chore`,
`security`. Scopes are free-form but kept short (e.g. `docker`,
`judge`).

## Pull requests

If you're not the project author, please open an issue first describing
what you'd like to change. The codebase is meant to stay small and
focused on the PFE scope; large refactors or new features are unlikely
to be merged without prior discussion.
