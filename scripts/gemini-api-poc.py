import os
import sys
import time
import json
import google.generativeai as genai

def test_api_poc():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("FAILURE: GEMINI_API_KEY not found in environment.")
        return False
        
    print("Configuring Gemini API...")
    genai.configure(api_key=api_key)
    
    # Use Flash model for speed/cost efficiency
    model_name = "models/gemini-2.5-flash" 
    print(f"Creating model: {model_name}")
    
    try:
        model = genai.GenerativeModel(model_name)
        
        prompt = 'Return (valid) JSON: {"status": "success"} #comment'
        print(f"Sending prompt: {prompt}")
        
        start_time = time.time()
        response = model.generate_content(prompt)
        end_time = time.time()
        
        print(f"Response received in {end_time - start_time:.4f} seconds.")
        print("Response Text:", response.text)
        
        # Verify JSON parseability
        # Note: SDK response.text might contain markdown
        try:
            from agentic_consult.utils import clean_json_output
            cleaned = clean_json_output(response.text)
            data = json.loads(cleaned)
            print("Parsed JSON:", data)
            if data.get("status") == "success":
                print("\nSUCCESS: API POC executed successfully.")
                return True
        except Exception as e:
            print(f"\nFAILURE: Could not parse response JSON: {e}")
            return False
            
    except Exception as e:
        print(f"\nFAILURE: API Call failed: {e}")
        return False

if __name__ == "__main__":
    # Ensure agentic_consult is in path for utils
    sys.path.append(os.getcwd())
    success = test_api_poc()
    sys.exit(0 if success else 1)
