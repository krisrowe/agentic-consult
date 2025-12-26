# Agentic Consult Project Status & Plans

---

## Post-Migration Fixes (2025-12-25)
- [x] **Fix Task Fetching**: `fetch_and_cache_tasks` warned "Expected list of tasks but got <class 'dict'>", resulting in empty task context. (Fixed by handling dict response)
- [x] **Fix TickTick Creation**: `ticktick task create` failed with exit status 2. (Fixed: Plural command + Positional argument)
- [x] **Fix Task Context Lifecycle**: Added a re-fetch of tasks after creation in `refresh` to ensure the next run has up-to-date context.
- [x] **Re-verify Refresh**: All TickTick integration issues are resolved and verified via sequential replay test.

## Future Architectural Improvements
- [ ] **Consolidate Precommit Scanning**: Migrate the customer-specific sensitive data scanning (names, slugs, keywords) from `consult precommit` into the `devws precommit` tool in the `ws-sync` repo.
    - **Analysis Phase**: Determine how `consult` can dynamically pass its customer configuration (names, slugs, keywords) to `devws precommit` at runtime, so `devws` can enforce a single, comprehensive scan.
    - **Implementation**: Augment `devws precommit` to accept dynamic patterns/keywords. Refactor `consult precommit` to act as a smart proxy that gathers context and delegates the actual scanning to `devws`.