import json
import logging
from agentic_consult.email.triage import suggest_email_action

# Suppress logging noise
logging.basicConfig(level=logging.ERROR)

print("--- Testing Ram Singh (Slack) ---")
res1 = suggest_email_action("19b90681f2f3a03c", profile="adc")
print(json.dumps(res1, indent=2))

print("\n--- Testing Package Delivery ---")
res2 = suggest_email_action("19b90599e0c80bc0", profile="adc")
print(json.dumps(res2, indent=2))
