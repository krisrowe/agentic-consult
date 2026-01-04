# Technical Debt

This document tracks known architectural issues and areas for improvement in the `agentic-consult` codebase.

## 1. Extract Business Logic into a Reusable SDK
- **Problem**: The `customers_refresh` command, now in `cli/refresh.py`, contains complex orchestration logic. This makes the CLI layer "thick," preventing the core logic from being reused by other potential entrypoints (e.g., a future web service).
- **Solution**:
    - Create a new `agentic_consult/sdk/` package.
    - Move all business logic (e.g., the high-level process of fetching, analyzing, and preparing a plan) into modules within this package (e.g., `sdk/refresh.py`).
    - The `cli` package should be responsible only for presentation: parsing arguments, calling the SDK, and displaying the results.
- **Principle**: The `sdk` package will contain the reusable core logic of the application, while the `cli` package will be a thin presentation layer.

## 2. Implement Email Content Batching
- **Problem**: When processing a large number of emails, the combined text can exceed the token limit of the language model.
- **Solution**:
    - Implement a batching mechanism in the core SDK (e.g., in the `refresh` orchestration module).
    - This mechanism should track the cumulative character count of emails being added to a prompt.
    - If a single email exceeds a configurable `max_email_chars` limit, it should be truncated with a warning.
    - The refresh process should loop, building and processing batches until all unprocessed emails are handled.

## 3. Refine `--message` Flag Logic for Efficient Isolation
- **Problem**: The `--message <id>` flag currently filters emails *after* a full fetch/load operation. This means all matching emails (e.g., all unread emails from a customer) are still downloaded or loaded from cache, even if only one specific email is targeted for processing. This is inefficient.
- **Solution**:
    - Modify the email fetching logic (e.g., in `gmail.py`) to pass the `--message <id>` constraint directly to the `gwsa` search query when this flag is used.
    - Ensure that when `--message <id>` is provided, only that specific email is fetched and subsequently processed, effectively bypassing unnecessary fetching, loading from cache, and batching logic for other emails.
    - The goal is true isolation and efficiency from the earliest possible stage in the refresh workflow.

## 4. Consolidate Security Scanning Logic
- **Problem**: Security scanning logic (detecting customer names, secrets, etc.) is currently duplicated or split between this repository (`agentic-consult`) and `ws-sync` (aka `devws`). This requires running multiple pre-commit checks (`consult precommit` and `devws precommit`).
- **Solution**: Unify the scanning logic.
    - **Option A**: Move the core scanner from `agentic-consult` into `ws-sync` and have `consult` delegate to it.
    - **Option B**: Extract the scanner into a shared library.
    - **Goal**: A single "precommit" command that covers all security checks, eliminating redundancy and ensuring consistent enforcement rules across tools.

- [ ] **Orphaned Backup File Handling**: In `UserHomeBackup`, detect files that exist on Drive but not locally. Implement a strategy for handling these orphans, such as prompting the user for deletion (in interactive mode) or skipping them. Consider a `--prune` flag for non-interactive cleanup. An alternative could be archiving all home files into a single `.zip` per run, similar to how repos are handled, which would simplify cleanup.

## 5. Consolidate Pre-commit Scanning
- **Problem**: `consult precommit` and `devws precommit` are separate commands with overlapping concerns.
- **Solution**: Have `consult precommit` proxy to `devws precommit` to avoid duplication.

## 6. Configuration Directory Separation

The current config/data separation is messy and the lines are blurring:

**Current State:**
- `settings.json` in XDG config dir controls where data lives
- `local_data` setting points to customer data (legacy customer configs)
- New files like `email.yaml` and `templates/` are hardcoded to XDG config dir
- No easy way to point config files to a different repo

**Desired State:**
- `settings.json` should be the only file required in XDG config dir
- Both `config_dir` and `data_dir` should be configurable via CLI (`consult config set`)
- User can point config (email.yaml, etc.) to a versioned repo
- Note: `templates/process_email.md` should be pkg-bundled, not user-managed (users configure via rules, not template)
- User can point data (customers/, cache files) to a separate location
- CLI is the primary interface for configuration - no reliance on env vars for normal use
- Env var logic may remain for testing and extensibility, but not required for typical workflows
- Cache location doesn't need to be configurable (XDG cache is fine)

**Why This Matters:**
- Want to version control email.yaml and templates in a config repo
- Don't want settings.json mixed in with versioned configs
- Legacy customer data management works but new email rules don't follow same pattern

## 7. Optimize Local-Only Backup Status Checks (Reduce Network I/O)
- **Context**: Currently, checking the status of a local-only repository (`consult repo-status`) requires making a Google Drive API call to fetch the `state_hash` from the remote bundle's `appProperties`. This adds latency and requires a network connection.
- **Proposal**:
    - Store the hash of the last successfully backed-up state locally (e.g., in `.git/config` via `git config consult.backup.last_hash` or a separate metadata file in `.gemini/`).
    - Allow status checks to compare the current repo state against this local record for an instant, offline "Clean" status.
    - Add a flag (e.g., `--verify-remote` or `--online`) to force the tool to double-check the actual file on Google Drive.
    - Alternatively, default to the safe network check but allow an `--offline` flag.
- **Goal**: Improve CLI responsiveness and support offline usage for status checks.

