from .analyzer import EmailAnalyzer
from email_archive import EmailStore
import logging
import os
import sys

# Configure basic logging for CLI visibility
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def main():
    # 1. Resolve overrides from Environment (Cloud Run friendly)
    # If not set, we pass None to let EmailAnalyzer use its own defaults
    limit_env = os.environ.get("ANALYZER_LIMIT")
    lookback_env = os.environ.get("ANALYZER_LOOKBACK_DAYS")
    
    limit = int(limit_env) if limit_env else None
    lookback = int(lookback_env) if lookback_env else None
    model = os.environ.get("ANALYZER_MODEL")
    
    # 2. Initialize Store and Analyzer
    store = EmailStore()
    analyzer = EmailAnalyzer(store, model=model)
    
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
