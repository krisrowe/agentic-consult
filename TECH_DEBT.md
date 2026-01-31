# Technical Debt & Roadmap

This document tracks known architectural issues and areas for improvement.

## 1. Email Processing & Triage

### Implement Email Content Batching
- **Problem**: Large email volumes exceed token limits.
- **Solution**: Implement a batching mechanism that tracks character counts and truncates/splits prompts intelligently.

### Refine `--message` Flag Logic
- **Problem**: The `--message <id>` flag filters *after* fetching.
- **Solution**: Pass the ID constraint directly to the `gwsa` search query for efficiency.

### Skip Re-evaluation of Labeled Emails
- **Problem**: Emails already marked `Reviewing` are re-sent to Gemini.
- **Solution**: Skip these in the prompt and return previous recommendations based on label state.

### Clean Up Gmail Labels on Archive
- **Problem**: Archiving doesn't remove the `Reviewing` label, polluting search results.
- **Solution**: Automatically remove `Reviewing` when archiving.

## 2. Infrastructure & Tooling

### Consolidate Security Scanning
- **Problem**: Logic duplicated between `agentic-consult` and `ws-sync`.
- **Solution**: Extract scanner into a shared library or have `consult` delegate to a unified tool.

### Network Sandboxing for Tests
- **Problem**: Tests might leak network calls.
- **Solution**: Use `pytest-socket` to enforce isolation.

### Optimize Local-Only Backup Checks
- **Problem**: `consult repo-status` hits Google Drive API for hashes (slow).
- **Solution**: Cache the last backup hash locally to allow offline "Clean" status checks.

### Orphaned Backup File Handling
- **Problem**: No strategy for cleaning up files on Drive that were deleted locally.
- **Solution**: Implement a prune strategy or zip-based archival.

## 3. Configuration & UX

### Configuration Directory Separation
- **Goal**: Allow `email.yaml` and rules to live in a versioned repo separate from `settings.json` (XDG).
- **Status**: Partially implemented (`config_dir` setting), needs CLI support.

### MCP Progress Indicators
- **Goal**: Report progress for long-running tools (like triage) to the client.
- **Blocker**: Requires `gwsa` to support streaming/callbacks and client support for progress tokens.

## 4. Logging & Observability

### Structured Triage Logging
- **Goal**: Log `message_id`, `rule_id`, and `action_taken` for every triage decision to enable effectiveness auditing.