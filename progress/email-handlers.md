# Design: Unified Email Processing & Handlers (LLM-Driven)

## Objective
Evolve the `agentic-consult` tool from a customer-specific refresher into a holistic, intelligent email assistant.
1.  **Intelligent Triage:** Use Gemini to classify and route emails, avoiding brittle regex rules.
2.  **Detect High-Priority Items:** Recognize direct requests, VIP communications, and urgent admin items (training, compliance) via semantic understanding.
3.  **Minimize Duplication:** Ensure each email is routed to exactly one Handler (Customer vs. General) based on its primary context.
4.  **Reusable Architecture:** Abstract the `Fetch -> Prompt -> Delta -> Task` loop.

---

## 1. New Architecture Overview

The system moves to a **"Triage & Dispatch"** model.

### A. The Core Pipeline
```mermaid
graph TD
    A[Global Gmail Fetch] --> B[Central Email Cache]
    B --> C[**LLM Triage Agent**]
    C -->|Output: Routing Plan| D{Router}
    
    D -- "Customer A" --> E[Customer Batch (A)]
    D -- "Customer B" --> F[Customer Batch (B)]
    D -- "General/Priority" --> G[General Priority Batch]
    D -- "Ignore" --> H[Archive/Skip]
    
    E --> I[Customer Processor (LLM)]
    F --> J[Customer Processor (LLM)]
    G --> K[General Processor (LLM)]
    
    I & J & K --> L[Task Manager (Local & TickTick)]
```

### B. Directory Structure
```text
~/.config/agentic-consult/
├── config.yaml             # Global settings (VIP names, broad definitions)
├── cache/                  # Centralized email storage
│   ├── inbox.json          # Raw emails
│   └── routing_log.json    # Record of how Gemini routed each email
├── customers/              # Existing customer configs
│   └── customer_a/
└── general/                # Storage for non-customer work
    ├── tasks/
    │   └── tasks.json      # General admin/priority tasks
```

---

## 2. The Logic Flow

### Step 1: Global Fetch (`agentic_consult.emails.fetcher`)
Fetch all unread/recent emails globally (e.g., `after:2d`).
- **Optimization:** Only fetch what hasn't been seen in `emails_processed.txt` (global or union of all local lists).

### Step 2: LLM Triage (`agentic_consult.router.llm`)
We send a **lightweight prompt** to Gemini with a batch of email metadata (Sender, Subject, Date, Snippet).

**System Prompt:**
> "You are an executive assistant's mail router.
> 
> **Your Goal:** Route each email to the single best category.
> 
> **Categories:**
> 1. **[Customer: <Name>]**: For work specifically related to defined customers.
> 2. **[Priority]**: For high-value items NOT related to a specific customer. This includes:
>    - Direct requests addressed to me.
>    - Emails from VIPs (Supervisor, Director).
>    - Compliance, Training, Expenses, HR, or Admin alerts.
> 3. **[Ignore]**: Newsletters, automated noise, or low-value blasts.
> 
> **Rules:**
> - **Specific Trumps General:** If a VIP asks about 'Customer A', route to 'Customer A'.
> - **Directness:** If an email is 'To' me, it's likely Priority unless it's clearly customer work.
> 
> **Input:** List of emails.
> **Output:** JSON mapping `email_id` -> `category`."

### Step 3: Dispatch & Processing
The Router reads Gemini's JSON response and pushes the *full* email content to the appropriate Handler queue.

**The Handlers:**
1.  **`CustomerHandler` (Existing Logic):**
    -   Receives: Emails routed to `[Customer: X]`.
    -   Context: Loads `customers/X/tasks.json` + Issues.
    -   Action: Creates/Updates tasks in the customer's project context.

2.  **`GeneralHandler` (New Logic):**
    -   Receives: Emails routed to `[Priority]`.
    -   Context: Loads `general/tasks/tasks.json`.
    -   Action: Creates tasks for things like "Complete Compliance Training", "Submit Timecard".
    -   *Feature:* Can apply labels (e.g., "Admin", "Urgent") based on the LLM's reasoning.

---

## 3. Configuration (`config.yaml`)

We simplify the config. We don't need regex rules. We just need **Definitions** for the LLM.

```yaml
# Global Task Settings
tasks:
  provider: ticktick
  cloud_sync: true
  default_project: "Work"

# Context for the Triage Agent
context:
  me: "My Name"
  vips:
    - "Manager Name (Manager)"
    - "Director Name (Director)"
  
  # Optional: Hints for the LLM if it gets confused
  routing_hints:
    - "Training emails usually come from training-platform"
    - "Expense reports come from finance-system"
```

---

## 4. Refactoring Plan

1.  **`agentic_consult.emails` Module:**
    -   Implement `GlobalFetcher`.
    -   Implement `LLMRouter`: Wraps the Triage Prompt.
2.  **`agentic_consult.handlers` Module:**
    -   `BaseHandler`: Common logic for Prompt -> Deltas -> Sync.
    -   `CustomerHandler`: Subclass with Issues context.
    -   `GeneralHandler`: Subclass for Admin/Priority tasks.
3.  **CLI Command `consult sync`:**
    -   Orchestrates: Fetch -> Triage -> Handler Execution -> Sync.

---

## 5. TickTick Integration
We maintain the separation of concerns via local files, but they sync to the same cloud project (or different ones if configured).
- **Tagging Strategy:** To visually distinguish them in the single "Work" project, the General Handler can auto-tag tasks as `#Admin` or `#General`, while Customer tasks get `#<CustomerSlug>`.

---

## 6. Advantages of LLM Triage
-   **Adaptability:** Detects "Urgent request from Manager" even if the subject doesn't match a regex.
-   **Contextual Routing:** Correctly routes "Can you help Customer A with X?" to Customer A, not General, because it understands the *entity* mentioned is a customer.
-   **Low Maintenance:** No need to write regex for every new training platform.