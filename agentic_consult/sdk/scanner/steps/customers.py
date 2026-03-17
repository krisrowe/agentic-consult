"""Customer pattern checks - names, slugs, keywords from customer.yaml files."""

from typing import List, Dict, Tuple

from ..utils import CheckResult, run_cmd, DIFF_METADATA_FILTER


def load_customer_patterns() -> Tuple[List[Dict], List[str]]:
    """Load patterns from all customer.yaml files."""
    try:
        from agentic_consult.customers import get_active_customers_root, _parse_customer_yaml
    except ImportError:
        return [], []

    customers_checked = []
    patterns = []

    root = get_active_customers_root()
    if not root.exists():
        return [], []

    for d in root.iterdir():
        if d.is_dir():
            c_yaml = d / "customer.yaml"
            if c_yaml.exists():
                try:
                    config = _parse_customer_yaml(c_yaml)
                    c_name = config.get('name')
                    c_slug = config.get('slug')

                    customers_checked.append({'name': c_name, 'slug': c_slug})

                    if c_name:
                        patterns.append(c_name)
                    if c_slug:
                        patterns.append(c_slug)

                    drive_id = config.get('drive_folder_id')
                    if drive_id:
                        patterns.append(drive_id)

                    for k in config.get('keywords', []):
                        patterns.append(k)

                except Exception:
                    pass

    return customers_checked, patterns


def check_customer_patterns(repo_path: str, patterns: List[str],
                            include_untracked: bool = False) -> CheckResult:
    """Check uncommitted content for customer patterns."""
    if not patterns:
        return CheckResult("Customer patterns", True, [], skipped=True,
                          info="No customer.yaml files found")

    findings = []
    grep_patterns = "|".join(patterns)

    cmd = f"git diff --cached -U0 | {DIFF_METADATA_FILTER} | grep -iE '{grep_patterns}'"
    rc, stdout, _ = run_cmd(cmd, repo_path)
    if rc == 0 and stdout.strip():
        for line in stdout.strip().split("\n")[:10]:
            findings.append(f"staged: {line[:100]}")

    cmd = f"git diff -U0 | {DIFF_METADATA_FILTER} | grep -iE '{grep_patterns}'"
    rc, stdout, _ = run_cmd(cmd, repo_path)
    if rc == 0 and stdout.strip():
        for line in stdout.strip().split("\n")[:10]:
            findings.append(f"unstaged: {line[:100]}")

    # Untracked files aren't staged and won't be in the commit —
    # scanning them is purely cautionary and off by default.
    if include_untracked:
        cmd = "git ls-files --others --exclude-standard"
        rc, stdout, _ = run_cmd(cmd, repo_path)
        if rc == 0 and stdout.strip():
            for f in stdout.strip().split("\n"):
                if f:
                    cmd2 = f"grep -iE '{grep_patterns}' '{f}' 2>/dev/null"
                    rc2, out2, _ = run_cmd(cmd2, repo_path)
                    if rc2 == 0 and out2.strip():
                        for line in out2.strip().split("\n")[:3]:
                            findings.append(f"{f}: {line[:80]}")

    passed = len(findings) == 0
    info = f"{len(patterns)} patterns from customer.yaml"
    return CheckResult("Customer patterns", passed, findings[:10], info=info)


def run_checks(repo_path: str, deep: bool = False,
               include_untracked: bool = False, **kwargs) -> List[CheckResult]:
    """Run all customer checks. Standard step interface."""
    _, patterns = load_customer_patterns()
    return [check_customer_patterns(repo_path, patterns,
                                    include_untracked=include_untracked)]
