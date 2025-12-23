import os
import sys
import yaml
import click
from pathlib import Path
from agentic_consult.config import load_main_config

DEFAULT_CUSTOMERS_DIR_NAME = "customers"

def get_active_customers_root():
    """
    Resolves the single authoritative root directory for customers.
    Priority:
    1. CUSTOMERS_DIR environment variable
    2. customers_local_path in config.yaml
    3. XDG App Config Directory / customers
    4. Local ./customers (fallback/legacy)
    """
    # 1. Env Var
    if os.environ.get("CUSTOMERS_DIR"):
        return Path(os.environ["CUSTOMERS_DIR"])

    # 2. Config
    main_config = load_main_config()
    custom_path = main_config.get("customers_local_path")
    if custom_path:
        return Path(custom_path)

    # 3. XDG (Preferred Default)
    xdg_root = Path(click.get_app_dir('agentic-consult')) / DEFAULT_CUSTOMERS_DIR_NAME
    
    # 4. Local fallback (only if XDG doesn't exist but local does, to support legacy dev usage)
    local_root = Path.cwd() / DEFAULT_CUSTOMERS_DIR_NAME
    if local_root.exists() and not xdg_root.exists():
        return local_root
        
    # Default to XDG
    return xdg_root

def load_customer_config(customers_dir=None):
    """
    Loads customer configuration from the active root or specific dir.
    """
    # Priority: CUSTOMER_FILE env var (direct override)
    if os.environ.get("CUSTOMER_FILE"):
        c_file = Path(os.environ["CUSTOMER_FILE"])
        if c_file.exists():
             return _parse_customer_yaml(c_file)

    root = Path(customers_dir) if customers_dir else get_active_customers_root()
    
    if not root.exists():
        return None
        
    for d in root.iterdir():
        if d.is_dir():
            c_yaml = d / "customer.yaml"
            if c_yaml.exists():
                return _parse_customer_yaml(c_yaml)
    return None

def find_customer_by_id(identifier):
    """Searches for a customer by slug or name in the active root."""
    root = get_active_customers_root()
    if not root.exists(): 
        return None
        
    for d in root.iterdir():
        if not d.is_dir(): continue
        c_yaml = d / "customer.yaml"
        if c_yaml.exists():
            cust = _parse_customer_yaml(c_yaml)
            if cust.get('slug') == identifier or cust.get('name') == identifier:
                return cust
    return None

def _parse_customer_yaml(path):
    # Import locally to avoid circular dependency
    from agentic_consult.schema import validate_yaml
    
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    
    try:
        validate_yaml(data, 'customer_schema.json')
    except Exception as e:
        # print(f"Warning: Customer config validation failed for {path}: {e}", file=sys.stderr)
        pass

    # Ensure keywords is a list
    if "keywords" in data and isinstance(data["keywords"], str):
        data["keywords"] = [data["keywords"]]
    elif "keywords" not in data:
        data["keywords"] = []
        
    return data