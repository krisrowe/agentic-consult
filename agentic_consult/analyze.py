import os
import glob
import yaml
from pathlib import Path
from agentic_consult.gemini import GeminiAPIClient
from agentic_consult.config import load_app_config

def load_analyze_config():
    """
    Loads analysis limits from project configuration.
    Defaults to 50 files and 1MB of content if not configured.
    """
    config = {
        "max_file_count": 50,
        "max_total_content_bytes": 1024 * 1024  # 1MB default
    }
    
    app_config = load_app_config()
    analyze_config = app_config.get("analyze", {})
    if analyze_config:
        config.update(analyze_config)
            
    return config

def run_analysis(prompt: str, resources: list[str], base_dir: str = None, model_name: str = None) -> dict:
    """
    Core analysis logic.
    Returns a dict with keys: 'response', 'stats' (dict), 'error' (str/None).
    """
    base = Path(base_dir) if base_dir else Path.cwd()
    config = load_analyze_config()
    max_files = config["max_file_count"]
    max_bytes = config["max_total_content_bytes"]

    context_files = [] # List of (filepath, size) tuples
    total_files = 0
    total_bytes = 0

    # 1. Resolve GEMINI.md
    # Priority: CWD, then parent of CWD
    gemini_candidates = [base / "GEMINI.md", base / "../GEMINI.md"]
    found_gemini_path = None
    
    for p in gemini_candidates:
        if p.exists() and p.is_file():
            found_gemini_path = p.resolve()
            size = p.stat().st_size
            
            total_files += 1
            total_bytes += size
            context_files.append((found_gemini_path, size))
            break
            
    # Phase 1: Discovery & Validation (Fail Fast)
    processed_paths = {str(found_gemini_path)} if found_gemini_path else set()

    for item in resources:
        item = item.strip()
        if not item: continue
        
        # Handle relative paths correctly
        full_pattern = str(base / item)
        
        # Expand globs
        matches = glob.glob(full_pattern, recursive=True)
        
        if not matches:
            # Check if it was a glob
            is_glob = any(char in item for char in ["*", "?", "["])
            if is_glob:
                return {"error": f"Glob pattern '{item}' matched no files."}
            else:
                return {"error": f"Path '{item}' does not exist."}
            
        for match in matches:
            match_path = Path(match)
            if match_path.is_dir():
                file_matches = glob.glob(str(match_path / "**" / "*.md"), recursive=True)
            else:
                file_matches = [str(match_path)]
                
            for filepath in file_matches:
                path_obj = Path(filepath)
                if not path_obj.is_file() or not path_obj.name.endswith(".md"):
                    continue
                    
                abs_path = str(path_obj.resolve())
                if abs_path in processed_paths:
                    continue
                
                size = path_obj.stat().st_size
                
                if total_files + 1 > max_files:
                    return {"error": f"File count limit exceeded ({max_files}). Analysis aborted."}
                
                if total_bytes + size > max_bytes:
                    return {"error": f"Total content size limit exceeded ({max_bytes} bytes). Analysis aborted."}

                total_files += 1
                total_bytes += size
                context_files.append((abs_path, size))
                processed_paths.add(abs_path)

    if not context_files:
        return {"error": "No context found (no GEMINI.md or matching markdown files)."}

    # Phase 2: Content Loading
    context = []
    for filepath, _ in context_files:
        try:
            with open(filepath, "r") as f:
                context.append(f"--- File: {filepath} ---\n{f.read()}\n")
        except Exception as e:
            # Log warning but continue? For now, we return error if critical read fails?
            # Or just skip. Let's skip and warn in stats.
            pass

    client = GeminiAPIClient(model_name=model_name)
    full_prompt = f"Context:\n\n{''.join(context)}\n\nQuestion: {prompt}"
    
    try:
        response = client.generate_content(full_prompt)
        return {
            "response": response["text"],
            "stats": {
                "file_count": total_files,
                "total_bytes": total_bytes,
                "model": client.model_name
            },
            "error": None
        }
    except Exception as e:
         return {"error": f"Error calling Gemini API: {e}"}
