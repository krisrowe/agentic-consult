import json
import yaml
import jsonschema
from pathlib import Path

def validate_yaml(yaml_data, schema_name):
    """
    Validates a python dict (from yaml) against a named schema resource.
    schema_name should be 'customer_schema.json' or 'config_schema.json'.
    """
    # Load schema from tests/schemas relative to package root? 
    # Or embed them in the package?
    # For now, let's look in tests/schemas if running from source, 
    # but ideally these should be package data if we want runtime validation in installed mode.
    
    # Try finding schema relative to this file
    base = Path(__file__).resolve().parents[1]
    schema_path = base / 'tests' / 'schemas' / schema_name
    
    if not schema_path.exists():
        # Fallback for installed package: look in agentic_consult/schemas (if we moved them)
        # or just fail gracefully for now
        return # Cannot validate if schema not found
        
    with open(schema_path, 'r') as f:
        schema = json.load(f)
        
    jsonschema.validate(instance=yaml_data, schema=schema)

def load_and_validate(path, schema_name):
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    validate_yaml(data, schema_name)
    return data
