# Agentic Consult Project Status & Plans

---

## Next Steps: Comprehensive Verification Sequence

### Phase 1: Local-Only Task Lifecycle (No Cloud Sync)
- [x] Wipe `emails_processed.txt`, `tasks.json`, and `issues/` for test customer.
- [x] Disable cloud sync in `config.yaml` (set `tasks: cloud_sync: false`).
- [x] Process Email 1: Verify `task_create` and local ID generation.
- [x] Process Email 2: Verify `task_update` references local ID correctly.
- [x] Process Sequence (10+ emails): Verify Story synthesis and context stability.
- [x] Verify `tasks.json` schema and data integrity after sequence.

### Phase 2: Independent Provider Sync Validation
- [x] **Automated Sync Test**: Create `tests/unit/tasks/test_tasks_cloud_sync.py`.
    - [x] Implement `test_create_and_update` method.
    - [x] Prepare a `deltas.json` with 3 task deltas: **1 task_create** and **2 task_updates**.
    - [x] Mock the TaskProvider and assert:
        - `add()` was called exactly once with the correct task data.
        - `update()` was called exactly twice with the correct task data and remote IDs.
        - Verify the exact arguments and call counts for each provider operation.
- [x] **Live Sync Test (Create & Update)**:
    - [x] Enable cloud sync in `config.yaml` (`tasks: cloud_sync: true`).
    - [x] **Step 1 (Create):** Process Email `19b4d241895a52ea` (Support Case). Verify task creation in TickTick.
    - [x] **Step 2 (Update):** Process Email `19b50b660c62deec` (Reply). Verify task update in TickTick.
    - [x] Verify `tasks.json` reflects remote IDs and `is_dirty: false` after sync.

### Phase 3: Full End-to-End Revalidation
- [ ] Repeat the 2-email sequence with cloud sync enabled from the start (effectively covered by Phase 2 Live Test, but confirming clean-slate behavior).
- [ ] Verify `emails_processed.txt` correctly prevents duplicates in a synced environment.

---

## Technical Tasks
- [x] **Verified**: Scanner catches customer names/slugs in tracked files.
- [x] **Verified**: Scanner respects `.gitignore`.
- [x] **Scanner Improvement**: Implement configurable allowlist for fake test data in `app.yaml`.
- [x] **Scanner Improvement**: Itemize checks and provide structured summary with icons (✅/❌).
- [x] **Test Coverage**: Added explicit exit code verification (Success/Fail/Multi-fail).
- [ ] **Refactor**: Consolidate `consult precommit` to proxy `devws precommit`.
- [x] **Config Cleanup**: 
    - [x] Remove `skip_task_writes` and `sync_tasks` from code and schemas.
    - [x] Refactor `app.yaml` and `config.yaml.example` to group settings under `tasks:` (`provider`, `cloud_sync`, `default_project`).
    - [x] Update `refresh.py` to use `dry_run` for all filesystem gates and `tasks.cloud_sync` for provider sync.

---

## Mandates
- **NO NEW TASK PROVIDERS** until this architecture is 100% verified.
- **DO NOT COMMIT THIS FILE.**
