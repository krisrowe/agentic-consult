import os
import pathspec
from pathlib import Path
from dataclasses import dataclass
import logging
from typing import List, Optional, Tuple, Callable, Union

logger = logging.getLogger(__name__)

@dataclass
class ContextItem:
    path: Path
    header_path: str
    content: Optional[str] = None
    is_binary: bool = False
    is_explicit: bool = False

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
    max_text_size_kb: int,
    max_binary_size_kb: int, 
    on_limit: str,
    header_path: str,
    is_explicit: bool = False,
    warning_callback: Optional[Callable[[str], None]] = None
) -> Optional[ContextItem]:
    """Checks and reads a single file, returning a ContextItem."""
    # 1. Check Exclusions
    if spec.match_file(header_path):
        logger.debug(f"Excluded: {header_path}")
        return None

    # 2. Check if file exists and is a file
    if not path.is_file():
        logger.debug(f"Not a file: {header_path}")
        return None

    # 3. Check Binary
    binary = is_binary(path)
    if binary and not is_explicit:
        logger.debug(f"Skipped Binary (Implicit): {header_path}")
        return None # Skip binary files found during directory walks

    # 4. Check Size
    try:
        size_kb = path.stat().st_size / 1024
    except OSError:
        return None

    limit_kb = max_binary_size_kb if binary else max_text_size_kb

    if size_kb > limit_kb:
        msg = f"File {header_path} exceeds size limit ({size_kb:.1f}KB > {limit_kb}KB)."
        if on_limit == "fail":
            raise ValueError(msg)
        elif on_limit == "warn":
            if warning_callback:
                warning_callback(f"Warning: {msg} Skipping.")
            logger.debug(f"Skipped (Size): {header_path}")
            return None
        else: # skip
            logger.debug(f"Skipped (Size): {header_path}")
            return None

    # 5. Handle Content
    if binary:
        logger.debug(f"Added Binary (Explicit): {header_path}")
        return ContextItem(path=path, header_path=header_path, is_binary=True, is_explicit=True)
    
    try:
        content = path.read_text(encoding='utf-8')
        logger.debug(f"Added Text: {header_path}")
        return ContextItem(path=path, header_path=header_path, content=content, is_binary=False, is_explicit=is_explicit)
    except Exception as e:
        if warning_callback:
            warning_callback(f"Warning: Could not read {header_path}: {e}")
        return None

def build_context(
    context_paths: List[str], 
    exclude_patterns: List[str], 
    max_text_size_kb: int = 100,
    max_binary_size_kb: int = 20480, 
    on_limit: str = "warn",
    warning_callback: Optional[Callable[[str], None]] = None
) -> List[ContextItem]:
    """
    Collects content from files and directories, respecting exclusions and limits.
    Returns a list of ContextItem objects.
    """
    spec = pathspec.PathSpec.from_lines('gitwildmatch', exclude_patterns)
    items = []
    cwd = Path.cwd()
    
    for entry in context_paths:
        p = Path(entry)
        if p.is_file():
            # Explicit File
            try:
                rel_path = p.relative_to(cwd)
                header = str(rel_path)
            except ValueError:
                header = str(p)
            
            item = process_file(p, spec, max_text_size_kb, max_binary_size_kb, on_limit, header, is_explicit=True, warning_callback=warning_callback)
            if item:
                items.append(item)
                logger.info(f"{header} - File Upload" if item.is_binary else f"{header} - Text Added")
                
        elif p.is_dir():
            # Directory Walk
            text_count = 0
            binary_skipped = 0
            
            for root, dirs, files in os.walk(p):
                root_path = Path(root)
                try:
                    rel_root = root_path.relative_to(cwd)
                except ValueError:
                    rel_root = root_path
                
                dirs[:] = [d for d in dirs if not spec.match_file(str(rel_root / d))]
                
                for file in files:
                    file_path = root_path / file
                    try:
                        rel_file = file_path.relative_to(cwd)
                        header = str(rel_file)
                    except ValueError:
                        header = str(file_path)
                        
                    # Pre-check binary for stats
                    if is_binary(file_path):
                        binary_skipped += 1
                        continue
                        
                    item = process_file(file_path, spec, max_text_size_kb, max_binary_size_kb, on_limit, header, is_explicit=False, warning_callback=warning_callback)
                    if item:
                        items.append(item)
                        text_count += 1
            
            logger.info(f"{entry} - Folder - {text_count} text files, {binary_skipped} binaries (skipped)")
                        
    return items
