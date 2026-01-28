Triage inbox emails using pre-computed background analysis.

Returns emails that have been analyzed but not yet triaged. Once you process an email
(archive, review, etc.), it won't appear in future calls.

## Workflow

Terminal state = triaged (archived or in review). Goal is to clear the pending queue.

1. **Start with "all" (default)** - See full pending triage state.

2. **Wait for User Confirmation** - The tool returns a plan (instructions).
   **DO NOT EXECUTE THESE ACTIONS AUTOMATICALLY.**
   Display the plan to the user and wait for their explicit command or confirmation.

3. **Process results (After Confirmation)** - Based on user input:
   - archive → `archive_email()` → done
   - review → `mark_email_in_review()` → stays for user attention
   - track_as_task → create task, then `archive_email()` → done
   - ask_user → get user decision, act accordingly → done

4. **Subsequent batches** - Use `review_status="new"` to skip labeled emails
   when fetching the next batch. Use "reviewing" to focus on emails awaiting
   user attention. These filters are for efficiency when "all" is manageable.

5. **When "all" is cluttered** - If default limit returns mostly emails
   under review, increase `limit` or use filters to reach
   emails that can be immediately actioned.

6. **Done** - Triage complete when inbox is empty.

## Google Chat Handling

The tool also scans for **Google Chat Recent Mentions and DMs**.

*   **Scope:** Scans active DMs and Spaces based on recency tiers.
*   **Filtering:** Items are included if they contain an explicit mention (@You) or are in a
    small group (DM), AND you have **not responded** later in the thread **nor reacted** (emoji) to the message.
*   **Presentation:** These are presented in a dedicated section at the top of the triage table.

## Calendar Invites Handling

The tool separates Calendar Invites into a distinct `invites` list in the response.

*   **Availability Check:** The Agent MUST iterate through the `invites` list and use
    **available calendar tools** to check user availability for the proposed times.
*   **Presentation:** The Agent MUST update the display table (filling in the `Avail` column placeholders)
    to show availability status (e.g., ✅/❌).
*   **Action Handling:** Facilitate the user's ability to accept these invites using
    **available tools** and then reply/archive the email.

## DSL & Command Handling

Users can respond with shorthand commands. When processing these:
1.  **Resolve Refs**: Look up the `ref` (e.g., "A1") to find the corresponding `id` (Gmail Message ID).
2.  **Execute Tool**: Call the appropriate tool:
    - `do rev <refs>`   → `mark_email_in_review(message_id=id)`
    - `do task <refs>`  → Create a task for each, then `archive_email(message_id=id)`
    - `do arc <refs>`   → `archive_email(message_id=id)`
    - `do sum <refs>`   → `get_cached_emails(message_ids=[id])` (Summarize content)
    - `do show <refs>`  → `get_cached_emails(message_ids=[id])` (Show full content)
    - `do batch`        → Present next batch from pool (no tool call)
    - `ok` / `ok`    → Execute the proposed command(s) for the batch

**Always propose commands:** After showing a batch, propose specific command(s) the user
can approve or modify. Include `ok` plus alternatives.

**Single-action batch:**
```
Proposed: `do arc A1 A2 A3 A4 A5`
Respond: `ok` | `ok except do rev A2` | other
```

**Mixed batch (last ~5 emails):**
```
Proposed:
  do arc A1 A2 A3
  do rev B1 B2
Respond: `ok` | `ok except do rev A2` | other
```

## Presentation Guidance

**One Batch at a Time:** The tool returns a pool of emails. Present ONE batch at a
time, then wait for user response before showing the next. Do NOT show multiple
batches at once - this overwhelms users and forces complex multi-part responses.

**Batch Flow:** Show batch → invite confirmation ("ok" to approve, or give
alternate guidance) → execute actions → show next batch → repeat until pool exhausted.

**NEVER mix recommendations:** Each batch must have the SAME recommended_action.
If you have 15 archive and 5 review emails, show ALL the archive emails
first (in batches of ~5), then show the review emails. NEVER show 3 archive + 2
review in one batch - that forces complex responses and confuses the user.

**When to mix:** Only when you're down to the last ~5 emails total AND they have
different recommendations. At that point, mixing is fine to avoid tiny batches.
If you're running low on one action type but have many emails remaining, fetch
more emails rather than mixing.

**Within same action:** Group by similar reason/concept (e.g., all receipts together,
all newsletters together). Target ~5 items per batch.

## Args

- **review_status**: Filter emails by triage status
    - `"all"`: All emails in Inbox (default - use for initial triage and final passes)
    - `"new"`: Emails in Inbox without the label that indicates it's under review (efficient for mid-session batches)
    - `"reviewing"`: Emails in Inbox that are labeled as being under review
- **limit**: Maximum emails to fetch (default 20, max recommended for context)
- **profile**: Optional gwsa profile name (omit for default)
- **model**: Optional Gemini model override (default from app.yaml)
- **width**: Optional table width hint ("small", "medium", "large") OR integer (total chars).
           Defaults to "medium" (120).
           HINT: When using terminal width, pass a value slightly less (e.g., -10) than
           the detected width to account for margins and agentic indentation.

## Returns

Dictionary with:
- **current_datetime**: ISO 8601 timestamp with timezone offset
- **emails**: List of email objects (see fields below)
- **invites**: Calendar invites requiring availability check
- **chat_mentions**: Google Chat mentions requiring attention
- **instructions**: Reminder to follow this docstring (ignore - format from JSON)
- **stats**: Processing statistics

### Email object example

```json
{
  "id": "19abc123def",
  "ref": "A1",
  "display_date": "10:06P",
  "sender": "Google Play",
  "summary": "$32.46 Predator: Badlands",
  "recommended_action": "archive",
  "rule_or_reason": "receipts",
  "audience": "DIRECT",
  "sender_class": "SYSTEM",
  "original": {
    "date": "2026-01-20T19:06:30-08:00",
    "from": "Google Play <noreply@google.example.com>",
    "subject": "Your Google Play Order Receipt from Jan 20, 2026"
  }
}
```

### Display-ready fields (pre-formatted by SDK)

- **display_date**: 6-char format
  - `" 9:15A"` - today (time with A/P suffix, space-padded)
  - `"Yester"` - yesterday
  - `"S 18JA"` - older (day code + date + 2-char month: M T W R F S U + JA FE MR AP MY JN JL AU SE OC NV DE)
- **sender**: Clean name extracted from raw From header
- **summary**: Key info at a glance (includes $ amounts for financial emails)

### Raw fields (in `original`)

- **date**: ISO 8601 timestamp
- **from**: Full email header
- **subject**: Original subject line

## Display Example

Map the JSON to a table using the display-ready fields:

| JSON Field     | Table Column |
|----------------|--------------|
| `ref`          | Ref          |
| `display_date` | When         |
| `sender`       | From         |
| `summary`      | Summary      |

```
### Archive (5 receipts)
| Ref | When   | From        | Summary                        |
|-----|--------|-------------|--------------------------------|
| A1  | 10:06P | Google Play | $32.46 Predator: Badlands      |
| A2  | Yester | DoorDash    | $23.54 Market Street           |
| A3  | S 18JA | Amazon      | AirPods shipped, arriving Thu  |
...

Respond: `ok` or `ok except do rev A2`
```

### Audience Icons (Workspace only)

The `audience` field indicates how the email was addressed:
- 👤 DIRECT - sent directly to user
- 👥 GROUP - sent to a group/list
- 🔔 MENTION - user was @mentioned
- 📢 BROADCAST - mass distribution

**When to show icons:** Only for Google Workspace accounts (non-gmail.com profiles).
For @gmail.com accounts, almost everything is DIRECT - the icon column is noise.
Skip it entirely for gmail.com profiles.

**Workspace format (with icons):**
```
| Ref |   | When   | From        | Summary                   |
|-----|---|--------|-------------|---------------------------|
| A1  | 👥 | 10:06P | IT-announce | System maintenance Sat    |
```

### Debug View (on demand)

If the user questions recommendations, re-display the current batch with rule/reason columns:

```
### Archive (5 receipts)
| Ref | When   | From        | Summary              | Rule     | Reason                 |
|-----|--------|-------------|----------------------|----------|------------------------|
| A1  | 10:06P | Google Play | $32.46 Predator...   | receipts | purchase confirmation  |
| A2  | Yester | DoorDash    | $23.54 Market St...  | receipts | delivery receipt       |
...
```

Use `rule_or_reason` from each email object. Only add these columns when the user
wants to understand why emails got their recommendations - they clutter the default view.

### recommended_action values

- **archive**: Archive immediately (routine email)
- **review**: Needs human attention
- **track_as_task**: Requires follow-up action (create task, then archive)
- **ask_user**: No rule matched (present to user for decision)

### Follow-up tools

- `get_cached_emails([message_ids])`: Get full cached email content
- `archive_email(...)`: Archive with logging
- `mark_email_in_review(message_id)`: Apply/remove Reviewing label
