"""
Test script to validate Gemini CLI context loading behavior.

Scenario:
- Producer: Has standard and custom context files.
- Consumer: Includes Producer directory and defines custom filenames.

Goal: Verify which files are loaded into context based on settings.
"""

import os
import json
import shutil
import subprocess
from pathlib import Path

BASE_DIR = Path("/tmp/gemini-context-test")
PRODUCER_DIR = BASE_DIR / "producer"
CONSUMER_DIR = BASE_DIR / "consumer"

def setup():
    if BASE_DIR.exists():
        shutil.rmtree(BASE_DIR)
    
    PRODUCER_DIR.mkdir(parents=True)
    CONSUMER_DIR.mkdir(parents=True)
    
    # --- Producer Setup ---
    # Standard context (Defaults should load this)
    (PRODUCER_DIR / "GEMINI.md").write_text(
        "# Producer Context\nFact: The capital of ProducerLand is ProdCity."
    )
    # Custom context (Defaults should IGNORE this)
    (PRODUCER_DIR / "CLIENT-CONTEXT.md").write_text(
        "# Producer Secrets\nFact: The secret code is Alpha99."
    )
    # No settings.json -> Defaults apply
    
    # --- Consumer Setup ---
    # Standard context
    (CONSUMER_DIR / "GEMINI.md").write_text(
        "# Consumer Context\nYou are a Consumer Agent."
    )
    # Custom local context
    (CONSUMER_DIR / "PERSONAL.md").write_text(
        "# Personal Info\nFact: Favorite color is Blue."
    )
    
    # Settings: NO includeDirectories, just registration
    consumer_settings = {
        "context": {
            "fileName": ["GEMINI.md", "PERSONAL.md", "CLIENT-CONTEXT.md"]
        }
    }
    
    (CONSUMER_DIR / ".gemini").mkdir()
    with open(CONSUMER_DIR / ".gemini/settings.json", "w") as f:
        json.dump(consumer_settings, f, indent=2)

def run_gemini(cwd, label):
    print(f"\n--- Running in {label} ({cwd}) ---")
    try:
        # Prompt designed to extract facts from all potential files
        prompt = "List all facts you know about capitals, secrets, and favorite colors. Be concise."
        
        result = subprocess.run(
            ["gemini", prompt], 
            cwd=cwd, 
            capture_output=True, 
            text=True,
            env=os.environ  # Pass current environment (API Keys)
        )
        print(f"EXIT CODE: {result.returncode}")
        print("OUTPUT:")
        print(result.stdout.strip())
        if result.stderr:
            print("STDERR:")
            print(result.stderr.strip())
            
    except Exception as e:
        print(f"Execution failed: {e}")

if __name__ == "__main__":
    import sys
    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: GEMINI_API_KEY environment variable not set.")
        print("Please set it before running this script: export GEMINI_API_KEY=your_key_here")
        sys.exit(1)

    setup()
    
    # 1. Producer Baseline
    run_gemini(PRODUCER_DIR, "Producer (Default Settings)")
    
    # 2. Consumer Baseline (via includeDirectories)
    run_gemini(CONSUMER_DIR, "Consumer (includeDirectories only)")
    
    # 3. Consumer with Symlink
    print("\n>>> Creating Symlink: consumer/CLIENT-CONTEXT.md -> ../producer/CLIENT-CONTEXT.md")
    try:
        (CONSUMER_DIR / "CLIENT-CONTEXT.md").symlink_to("../producer/CLIENT-CONTEXT.md")
        run_gemini(CONSUMER_DIR, "Consumer (with Symlink)")
    except FileExistsError:
        print("Symlink creation failed (file exists).")
    except Exception as e:
        print(f"Symlink error: {e}")
