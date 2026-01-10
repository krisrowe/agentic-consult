import json
import yaml
import jsonschema
from pathlib import Path

def validate_yaml(yaml_data, schema_name):
    """
    Validates a python dict (from yaml) against a named schema resource.
    schema_name should be 'customer_schema.json', 'config_schema.json', or 'app_schema.json'.
    """
    # Try finding schema relative to this file in the schemas/ subdirectory
    base = Path(__file__).resolve().parent
    schema_path = base / 'schemas' / schema_name
    
    if not schema_path.exists():
        logger.warning(f"Schema not found: {schema_path}")
        return # Cannot validate if schema not found
        
    with open(schema_path, 'r') as f:
        schema = json.load(f)
        
    jsonschema.validate(instance=yaml_data, schema=schema)

def load_and_validate(path, schema_name):
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    validate_yaml(data, schema_name)
    return data
