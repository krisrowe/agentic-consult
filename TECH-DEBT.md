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

- [ ] **Orphaned Backup File Handling**: In `UserHomeBackup`, detect files that exist on Drive but not locally. Implement a strategy for handling these orphans, such as prompting the user for deletion (in interactive mode) or skipping them. Consider a `--prune` flag for non-interactive cleanup. An alternative could be archiving all home files into a single `.zip` per run, similar to how repos are handled, which would simplify cleanup.

