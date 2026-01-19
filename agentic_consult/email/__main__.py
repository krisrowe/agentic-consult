from .analyzer import EmailAnalyzer, GeminiProvider
from email_archive import EmailStore
import logging
import os
import sys

# Configure logging - respect LOG_LEVEL env var (default INFO)
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, log_level, logging.INFO), format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def main():
    # PII logging notices
    from agentic_consult.logging import log_feature_notice
    log_feature_notice("INFO_LOG_EMAIL_SUBJECT", "email subjects will be logged (may contain PII)", "EMAIL_PII_LOG_NOTICE")
    log_feature_notice("INFO_LOG_EMAIL_SENDER", "email senders will be logged (contains PII)", "EMAIL_PII_LOG_NOTICE")

    # 1. Resolve overrides from Environment (Cloud Run friendly)
    # If not set, we pass None to let EmailAnalyzer use its own defaults
    limit_env = os.environ.get("ANALYZER_LIMIT")
    lookback_env = os.environ.get("ANALYZER_LOOKBACK_DAYS")

    limit = int(limit_env) if limit_env else None
    lookback = int(lookback_env) if lookback_env else None
    model = os.environ.get("ANALYZER_MODEL")

    # 2. Initialize Store and Analyzer
    store = EmailStore()
    provider = GeminiProvider(model=model)  # model can be None, uses default
    analyzer = EmailAnalyzer(store, provider=provider)
    
    # 3. Execution
    print(f"Starting Email Analysis loop...")
    print(f"  Storage: {store.root}")
    
    result = analyzer.process_queue(lookback_days=lookback, limit=limit)
    
    processed = result.get("processed", 0)
    if processed > 0:
        print(f"✅ Success: Analyzed {processed} emails.")
    else:
        print(f"ℹ️ Idle: No new emails found needing analysis.")

if __name__ == "__main__":
    main()
