import os
import pathspec
from pathlib import Path
from typing import List, Optional, Tuple, Callable

def is_binary(path: Path) -> bool:
    """Detect binary files using the null-byte heuristic (first 8KB)."""
    try:
        with open(path, 'rb') as f:
            chunk = f.read(8192)
            return b'\x00' in chunk
    except Exception:
        return True # Treat as binary if we can't read it

def process_file(
    path: Path, 
    spec: pathspec.PathSpec, 
    max_size_kb: int, 
    on_limit: str,
    header_path: str,
    warning_callback: Optional[Callable[[str], None]] = None
) -> Optional[str]:
    """Checks and reads a single file, returning its formatted content for the prompt."""
    # 1. Check Exclusions
    if spec.match_file(header_path):
        return None

    # 2. Check if file exists and is a file
    if not path.is_file():
        return None

    # 3. Check Binary
    if is_binary(path):
        return None

    # 4. Check Size
    try:
        size_kb = path.stat().st_size / 1024
    except OSError:
        # Handle cases where file might disappear or be inaccessible
        return None

    if size_kb > max_size_kb:
        msg = f"File {header_path} exceeds size limit ({size_kb:.1f}KB > {max_size_kb}KB)."
        if on_limit == "fail":
            raise ValueError(msg)
        elif on_limit == "warn":
            if warning_callback:
                warning_callback(f"Warning: {msg} Skipping.")
            return None
        else: # skip
            return None

    # 5. Read Content
    try:
        content = path.read_text(encoding='utf-8')
        return f"--- File: {header_path} ---\n{content}\n"
    except Exception as e:
        if warning_callback:
            warning_callback(f"Warning: Could not read {header_path}: {e}")
        return None

def build_context(
    context_paths: List[str], 
    exclude_patterns: List[str], 
    max_size_kb: int = 100, 
    on_limit: str = "warn",
    warning_callback: Optional[Callable[[str], None]] = None
) -> List[str]:
    """
    Collects content from files and directories, respecting exclusions and limits.
    Returns a list of formatted strings (chunks).
    """
    spec = pathspec.PathSpec.from_lines('gitwildmatch', exclude_patterns)
    context_chunks = []
    cwd = Path.cwd()
    
    for entry in context_paths:
        p = Path(entry)
        if p.is_file():
            # Use relative path for spec check and header if it's under CWD
            try:
                rel_path = p.relative_to(cwd)
                header = str(rel_path)
            except ValueError:
                header = str(p)
            
            chunk = process_file(p, spec, max_size_kb, on_limit, header, warning_callback)
            if chunk:
                context_chunks.append(chunk)
        elif p.is_dir():
            # Walk directory recursively
            for root, dirs, files in os.walk(p):
                # Ensure we have a path object for the current root
                root_path = Path(root)
                try:
                    rel_root = root_path.relative_to(cwd)
                except ValueError:
                    rel_root = root_path
                
                # Filter directories in-place for os.walk performance
                dirs[:] = [d for d in dirs if not spec.match_file(str(rel_root / d))]
                
                for file in files:
                    file_path = root_path / file
                    try:
                        rel_file = file_path.relative_to(cwd)
                        header = str(rel_file)
                    except ValueError:
                        header = str(file_path)
                        
                    chunk = process_file(file_path, spec, max_size_kb, on_limit, header, warning_callback)
                    if chunk:
                        context_chunks.append(chunk)
                        
    return context_chunks
