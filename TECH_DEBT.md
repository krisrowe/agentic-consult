# Tech Debt

## Email Triage Optimizations

### Cache emails between triage calls
Currently each `triage_emails` call fetches from Gmail API. Should cache fetched emails locally so subsequent calls (within same session or short window) don't re-fetch the same emails.

### Skip re-evaluation of labeled emails in Gemini
Emails already marked Reviewing or Archivable get sent to Gemini again on each call. Could skip these in the Gemini prompt and just return their previous recommendation based on label state, only re-evaluating Archivable emails to check if they've aged into archive_now.

### Track expected archive dates for Archivable emails
If we log when an email was marked Archivable and the rule's age threshold, we could calculate the expected archive_now date and skip Gemini evaluation until then.

## Logging Improvements

### Add structured logging for triage workflow
Log each recommendation and action taken with:
- message_id
- recommended_action
- rule_id (if matched)
- action_taken (archive, label applied, task created)
- timestamp

Enables audit trail and debugging of rule effectiveness.
