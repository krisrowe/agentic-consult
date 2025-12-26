# Agentic Consult Project Status & Plans

---

## Future Architectural Improvements
- [ ] **Consolidate Precommit Scanning**: Migrate the customer-specific sensitive data scanning (names, slugs, keywords) from `consult precommit` into the `devws precommit` tool in the `ws-sync` repo.
    - **Analysis Phase**: Determine how `consult` can dynamically pass its customer configuration (names, slugs, keywords) to `devws precommit` at runtime, so `devws` can enforce a single, comprehensive scan.
    - **Implementation**: Augment `devws precommit` to accept dynamic patterns/keywords. Refactor `consult precommit` to act as a smart proxy that gathers context and delegates the actual scanning to `devws`.
