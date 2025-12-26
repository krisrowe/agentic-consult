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
    - Implement `test_create_and_update` method.
    - Prepare a `deltas.json` with 3 task deltas: **1 task_create** and **2 task_updates**.
    - Mock the TaskProvider and assert:
        - `add()` was called exactly once with the correct task data.
        - `update()` was called exactly twice with the correct task data and remote IDs.
        - Verify the exact arguments and call counts for each provider operation.
- [ ] Enable cloud sync in `config.yaml` (set `tasks: cloud_sync: true` and `tasks: provider: ticktick`).
- [ ] Pre-Analysis Sync: Pull manually created remote tasks into `tasks.json`.
- [ ] Post-Analysis Sync: Push local tasks (`provider_id: null`) and capture remote IDs.
- [ ] Update Sync: Modify local task and verify `is_dirty` triggers remote update.
- [ ] Conflict Resolution: Test behavior when local and remote tasks are both modified.

### Phase 3: Full End-to-End Revalidation
- [ ] Repeat 10+ email sequence with cloud sync enabled.
- [ ] Verify TickTick dashboard matches local `tasks.json` state exactly.
- [ ] Verify `emails_processed.txt` correctly prevents duplicates in a synced environment.

---

## Technical Tasks
- [x] **Verified**: Scanner catches customer names/slugs in tracked files.
- [x] **Verified**: Scanner respects `.gitignore`.
- [ ] **Scanner Improvement**: Implement configurable allowlist for fake test data.
- [ ] **Refactor**: Consolidate `consult precommit` to proxy `devws precommit`.
- [x] **Config Cleanup**: 
    - [x] Remove `skip_task_writes` and `sync_tasks` from code and schemas.
    - [x] Refactor `app.yaml` and `config.yaml.example` to group settings under `tasks:` (`provider`, `cloud_sync`, `default_project`).
    - [x] Update `refresh.py` to use `dry_run` for all filesystem gates and `tasks.cloud_sync` for provider sync.

---

## Mandates
- **NO NEW TASK PROVIDERS** until this architecture is 100% verified.
- **DO NOT COMMIT THIS FILE.**