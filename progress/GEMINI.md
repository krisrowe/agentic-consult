# Agentic Consult - Progress & Status

This directory (`progress/`) contains work-in-progress artifacts, Proof-of-Concept (POC) scripts, and temporary documentation. These files are safe for public history but are intended for eventual removal or integration into the main codebase.

**Note**: We plan to `git rm` this entire folder once the system reaches a stable state where unit tests, integration tests, and live end-to-end tests are all consistently passing.

**Current Artifacts:**
- `gemini-cli-test.py`: Verifies local `gemini` CLI wrapper execution.
- `gemini-api-poc.py`: Performance comparison using `google-generativeai` SDK.

---

# Project Handoff Status

## Snapshot: 2025-12-24 12:45 UTC

**Test Status**: ALL GREEN ✅
- **Unit Tests**: 24/24 PASSED (`tests/unit`)
- **Integration Tests**: 1/1 PASSED (`tests/integration`)
- **Gemini CLI Test**: PASSED (`progress/gemini-cli-test.py`)

## Current Status: Features Implemented & Verified ✅

**Branch**: main

## What Was Completed

### 1. New Email-Centric Response Format ✅
**Files**: 
- `agentic_consult/cli/refresh.py`
- `agentic_consult/prompt.tpl`
- `tests/integration/test_gemini_integration.py`

**Status**: **DONE**
The system now uses the new email-centric JSON format. `process_deltas` handles it correctly.

### 2. `--retry-deltas` with Optional Path ✅
**File**: `agentic_consult/cli/refresh.py`

**Status**: **DONE**
Implemented `--retry-deltas [PATH]`. Supports resuming from a specific file, skipping fetch/LLM.

### 3. Gemini CLI Integration ✅
**File**: `agentic_consult/cli/refresh.py`

**Status**: **DONE**
Now invokes `gemini` CLI directly using `subprocess.run`.
- MCP servers and extensions are explicitly disabled (`--allowed-mcp-server-names=""`).
- `stdout` is captured for the response.
- `stderr` streams to console for visibility.

### 4. Robust JSON Parsing ✅
**File**: `agentic_consult/utils.py` & `agentic_consult/cli/refresh.py`

**Status**: **DONE & Wired Up**
`clean_json_output` is now used in `process_deltas` and acknowledgment tracking.
This handles cases where the LLM outputs conversational preamble or markdown blocks before the JSON.
This fixed the integration test failures.

### 5. Gemini CLI Integration Script ✅
**File**: `progress/gemini-cli-test.py`

**Status**: **Committed**
A standalone script to verify the local `gemini` CLI environment and subprocess execution.
Run with: `python3 progress/gemini-cli-test.py`

### 6. Gemini API (SDK) Comparison POC ✅
**File**: `progress/gemini-api-poc.py`

**Status**: **Committed (Experimental)**
A script using the `google-generativeai` SDK to compare performance against the CLI wrapper.
**Findings**:
- **Model**: `gemini-2.5-flash`
- **API (SDK)**: ~3.1s total execution (~0.7s latency).
- **CLI Wrapper**: ~4.9s total execution.
- **Recommendation**: The API approach is faster and cleaner. Migrating to the SDK is a valid optimization.

## Artifact Management
The following scripts are temporary development artifacts and should eventually be removed after explicit approval:
- `progress/gemini-cli-test.py`
- `progress/gemini-api-poc.py`

## Outstanding Work - Priority Order

### Priority 1: Enhanced Email Processing Flow
**Status**: Documented but not implemented
**File**: `temp/missing-features.md`

**Proposed flow**:
1. **Build candidate list**: Gmail query + local disk emails
2. **De-duplicate**: Mark which are cloud-only, disk-only, or both
3. **Flag processed**: Check against `emails_processed.txt`
4. **Report stats**: Show counts (total, cloud, disk, processed, to-process)
5. **Filter**: Remove already processed
6. **Load efficiently**: Read from disk if available, else fetch from cloud
7. **Progress indicator**: "Loading emails: 3/10 (30%)" (single line updates)

### Priority 2: Final Cleanup
- Review `temp/` folder and delete remaining temporary docs (`new-response-format.md`, `missing-features.md`, etc.) if their content is captured in code or issues.
- `MANIFEST.in` was added to include `agentic_consult/prompt.tpl`. Verify packaging works.

## Verification

Run all tests:
```bash
PYTHONPATH=. .venv/bin/pytest tests/unit tests/integration -v
```