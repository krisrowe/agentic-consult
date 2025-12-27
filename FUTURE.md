# Future Roadmap and Ideas

This document captures high-level feature ideas, architectural proposals, and future directions for the agentic consulting toolkit.

## Specialized Agents

### Task Analysis Agent (TickTick Integration)
Build a specialized tool or agent (possibly within the `ticktick-access` repo) that manages a local cache of all tasks in a project/list.

-   **Operation**: Reactively or scheduled refresh of task data into an XDG-compliant cache.
-   **Intelligence**: Enables complex, natural language querying of the entire task history (including completed tasks) without overfilling the primary agent's context window.
-   **Pattern**: Implements an "agent-to-agent" interaction pattern where the primary agent delegates deep task analysis to this specialized component.
-   **Advantage**: Significant reduction in primary context pollution and eliminated need for the primary agent to understand low-level task synchronization/refresh mechanics.
-   **Research**: Investigate if Google SDKs or existing agentic frameworks support this pattern natively to avoid redundant overhead.

## Backup System Enhancements

### Orphaned Backup File Handling
In `UserHomeBackup`, detect files that exist on Drive but not locally. Implement a strategy for handling these orphans, such as prompting the user for deletion (in interactive mode) or skipping them. Consider a `--prune` flag for non-interactive cleanup. An alternative could be archiving all home files into a single `.zip` per run, similar to how repos are handled, which would simplify cleanup.
