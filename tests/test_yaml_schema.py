import pytest
from pathlib import Path
from agentic_consult.schema import load_and_validate

ROOT = Path(__file__).resolve().parents[1]

def test_customer_example_matches_schema():
    example_path = ROOT / 'customer.yaml.example'
    assert example_path.exists()
    load_and_validate(example_path, 'customer_schema.json')

def test_config_example_matches_schema():
    example_path = ROOT / 'config.yaml.example'
    assert example_path.exists()
    load_and_validate(example_path, 'config_schema.json')

def test_app_config_matches_schema():
    app_yaml_path = ROOT / 'agentic_consult' / 'app.yaml'
    assert app_yaml_path.exists()
    load_and_validate(app_yaml_path, 'app_schema.json')
