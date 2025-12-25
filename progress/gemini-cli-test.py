import subprocess
import json
import sys

def test_no_shell():
    # Prompt with shell-sensitive characters
    prompt = 'Return (valid) JSON: {"status": "success"} #comment'
    cmd = ["gemini", prompt, "--allowed-mcp-server-names", "", "--extensions", ""]
    
    print(f"Executing: {cmd}")
    
    try:
        # shell=False (default)
        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True
        )
        
        print("Exit Code:", process.returncode)
        print("STDOUT:", process.stdout)
        print("STDERR:", process.stderr)
        
        if process.returncode == 0:
             print("\nSUCCESS: Gemini CLI executed successfully.")
             return True
        else:
             print("\nFAILURE: Gemini CLI returned non-zero exit code.")
             return False
             
    except FileNotFoundError:
        print("\nFAILURE: 'gemini' executable not found in PATH.")
        return False

if __name__ == "__main__":
    success = test_no_shell()
    sys.exit(0 if success else 1)

