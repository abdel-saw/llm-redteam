# Pre-commit hook for Red-Agent-S — PowerShell variant.
#
# Strategy: delegate to bash if available (Git for Windows ships one);
# otherwise re-implement the same scan in pure PowerShell so users on a
# bash-less Windows can still benefit from the guard.

$ErrorActionPreference = "Stop"

$bashCmd = Get-Command bash -ErrorAction SilentlyContinue
if ($bashCmd) {
    & $bashCmd.Source ".githooks/pre-commit"
    exit $LASTEXITCODE
}

# ------------------- Pure-PowerShell fallback -----------------------------

$patterns = @(
    'gsk_[A-Za-z0-9]{30,}',
    'sk-[A-Za-z0-9]{30,}',
    'sk-or-v1-[A-Za-z0-9]{20,}',
    'sk-ant-[A-Za-z0-9_-]{20,}',
    'AKIA[0-9A-Z]{16}',
    'ghp_[A-Za-z0-9]{36}',
    'Bearer [A-Za-z0-9._-]{40,}'
)
$whitelist = 'FAKER|REDACTED|EXAMPLE|DUMMY|PLACEHOLDER|xxxxx|TEST_|test_|fake'

function Get-Preview {
    param([string]$value)
    if ($value.Length -le 12) { return $value }
    return $value.Substring(0, 6) + "..." + $value.Substring($value.Length - 4)
}

$files = git diff --cached --name-only --diff-filter=ACM
if (-not $files) { exit 0 }

$totalFound = 0
foreach ($file in $files) {
    if (-not $file) { continue }
    $diff = git diff --cached -- $file
    if (-not $diff) { continue }
    # Binary file marker
    $head = $diff | Select-Object -First 5
    if ($head -match '^Binary files') { continue }

    $added = $diff | Where-Object { $_ -match '^\+' -and $_ -notmatch '^\+\+\+' }
    if (-not $added) { continue }

    foreach ($pattern in $patterns) {
        $matches = $added | Select-String -Pattern $pattern
        foreach ($m in $matches) {
            $line = $m.Line
            if ($line -match $whitelist) { continue }
            $matched = $m.Matches[0].Value
            $preview = Get-Preview -value $matched
            $offending = $line.TrimStart('+')
            if ($offending.Length -gt 120) { $offending = $offending.Substring(0, 120) }
            [Console]::Error.WriteLine("Potential secret detected in $file")
            [Console]::Error.WriteLine("   Pattern: $pattern")
            [Console]::Error.WriteLine("   Match preview: $preview")
            [Console]::Error.WriteLine("   Offending line (truncated): $offending")
            [Console]::Error.WriteLine("   If intentional (test fixture), include FAKER, REDACTED,")
            [Console]::Error.WriteLine("   EXAMPLE, DUMMY, PLACEHOLDER, TEST_, or `"fake`" in the value.")
            [Console]::Error.WriteLine("")
            $totalFound = 1
        }
    }
}

if ($totalFound -ne 0) {
    [Console]::Error.WriteLine("Commit blocked by .githooks/pre-commit.ps1.")
    [Console]::Error.WriteLine("Run with --no-verify only if you have manually verified that no real key is being committed.")
    exit 1
}
exit 0
