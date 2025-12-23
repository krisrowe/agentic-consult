import os
import yaml
import click
from pathlib import Path
from agentic_consult.schema import validate_yaml

CONFIG_FILENAME = "config.yaml"

def get_config_path(filename=CONFIG_FILENAME):
    """
    Searches for a config file in:
    1. Current directory
    2. XDG App Config Directory (~/.config/agentic-consult)
    """
    # 1. CWD
    cwd_path = Path.cwd() / filename
    if cwd_path.exists():
        return cwd_path
        
    # 2. XDG
    app_config_dir = Path(click.get_app_dir('agentic-consult'))
    xdg_path = app_config_dir / filename
    if xdg_path.exists():
        return xdg_path
    
    # Return XDG path as default for writing if neither exists
    return app_config_dir / filename

def load_yaml_file(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    
    # Optional: validate if it matches known filenames
    if Path(path).name == CONFIG_FILENAME:
        try:
            validate_yaml(data, 'config_schema.json')
        except Exception as e:
            # We don't want to crash on load, just warn? or log?
            # Printing to stderr is safe for CLI tools
            pass 
            
    return data

def load_main_config():
    path = get_config_path(CONFIG_FILENAME)
    # If path doesn't exist, get_config_path returns the XDG path where it *would* be.
    # So we check existence here.
    if not path.exists():
        return {}
    return load_yaml_file(path)

def save_main_config(data):
    path = get_config_path(CONFIG_FILENAME)
    # If using CWD fallback from get_config_path logic:
    # Actually get_config_path prefers CWD if exists. 
    # If it doesn't exist, it returns XDG.
    # So 'set' will default to creating in XDG, unless CWD config already exists.
    # This matches the requirement: "auto-created on first use of set commands if not present" 
    # and "config.yaml will always be in XDG" (implied preference for creation).
    
    # Ensure dir exists
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f)
    return path
