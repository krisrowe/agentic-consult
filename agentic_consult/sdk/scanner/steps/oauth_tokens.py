"""OAuth token and API key checks."""

from typing import List

from ..utils import CheckResult, run_cmd, DIFF_METADATA_FILTER


def check_oauth_tokens(repo_path: str) -> CheckResult:
    """Check for OAuth tokens and API keys."""
    token_patterns = [
        (r'ya29\.[a-zA-Z0-9_-]+', "Google OAuth"),
        (r'ghp_[a-zA-Z0-9]{36}', "GitHub PAT"),
        (r'github_pat_[a-zA-Z0-9_]+', "GitHub fine-grained"),
        (r'sk-[a-zA-Z0-9]{48}', "OpenAI key"),
        (r'AIza[a-zA-Z0-9_-]{35}', "Google API key"),
        (r'xox[bp]-[a-zA-Z0-9-]+', "Slack token"),
    ]

    findings = []
    for pattern, name in token_patterns:
        cmd = f"git diff --staged 2>/dev/null | {DIFF_METADATA_FILTER} | grep -oE '{pattern}' | head -5"
        rc, stdout, _ = run_cmd(cmd, repo_path)
        if stdout.strip():
            for match in stdout.strip().split("\n")[:2]:
                # Truncate for display
                truncated = match[:20] + "..." if len(match) > 20 else match
                findings.append(f"{name}: {truncated}")

    passed = len(findings) == 0
    return CheckResult("OAuth/API tokens", passed, findings[:10])


def run_checks(repo_path: str, deep: bool = False, **kwargs) -> List[CheckResult]:
    """Run all OAuth/token checks. Standard step interface."""
    return [check_oauth_tokens(repo_path)]
