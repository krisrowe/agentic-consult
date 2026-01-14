"""Tests for app.yaml schema strictness.

NOTE: conftest.py auto-sets CONSULT_CONFIG_DIR for every test.
Use the `config_dir` fixture to get the isolated config path.
"""
import json
import yaml
import pytest
from pathlib import Path
from jsonschema import ValidationError
from agentic_consult.config import load_app_config


def test_load_app_config_rejects_additional_properties(config_dir):
    """
    Verify that load_app_config raises ValidationError if additional
    properties are present in app.yaml.
    """
    app_yaml = config_dir / "app.yaml"

    # 1. Start with a minimal valid config (matching existing app.yaml structure)
    valid_data = {
        "gemini": {
            "models": {
                "default": "gemini-2.0-flash",
                "available": ["gemini-2.0-flash"]
            }
        }
    }

    with open(app_yaml, "w") as f:
        yaml.dump(valid_data, f)

    # Should pass initially (even if loose)
    data = load_app_config()
    assert data["gemini"]["models"]["default"] == "gemini-2.0-flash"

    # 2. Inject junk at root
    valid_data["junk_root"] = "should_fail"
    with open(app_yaml, "w") as f:
        yaml.dump(valid_data, f)

    # EXPECT FAILURE: This should raise ValidationError if schema is strict
    with pytest.raises(ValidationError):
        load_app_config()


def test_load_app_config_rejects_nested_additional_properties(config_dir):
    """
    Verify that load_app_config raises ValidationError if additional
    properties are present in nested objects.
    """
    app_yaml = config_dir / "app.yaml"

    valid_data = {
        "gemini": {
            "models": {
                "default": "gemini-2.0-flash",
                "available": ["gemini-2.0-flash"],
                "junk_nested": "should_fail"
            }
        }
    }

    with open(app_yaml, "w") as f:
        yaml.dump(valid_data, f)

    # EXPECT FAILURE
    with pytest.raises(ValidationError):
        load_app_config()


def test_schema_disallows_additional_properties_globally(config_dir):
    """
    Systematically verify that every object defined in the schema has
    additionalProperties: false by attempting to inject junk at every path.
    """
    schema_path = Path(__file__).resolve().parents[2] / "agentic_consult" / "schemas" / "app_schema.json"
    with open(schema_path) as f:
        schema = json.load(f)

    def get_object_paths(s, path=None):
        """Recursively find paths to all object definitions in the schema."""
        if path is None:
            path = []
        paths = []

        if s.get("type") == "object":
            paths.append(path)
            if "properties" in s:
                for prop, sub in s["properties"].items():
                    paths.extend(get_object_paths(sub, path + [prop]))
            if "items" in s:  # Handle arrays of objects
                paths.extend(get_object_paths(s["items"], path + ["_items_"]))
        return paths

    def build_valid_minimal(s):
        """Build a minimal valid object for a schema node."""
        if s.get("type") == "object":
            obj = {}
            for prop, sub in s.get("properties", {}).items():
                # For required fields or simple structure, just provide a dummy
                if sub.get("type") == "string":
                    obj[prop] = "val"
                elif sub.get("type") == "boolean":
                    obj[prop] = True
                elif sub.get("type") == "integer":
                    obj[prop] = 1
                elif sub.get("type") == "array":
                    obj[prop] = []
                elif sub.get("type") == "object":
                    obj[prop] = build_valid_minimal(sub)
            return obj
        return "val"

    def inject_junk(data, path):
        """Inject a junk key at the end of the provided path."""
        target = data
        for step in path:
            if step == "_items_":
                if isinstance(target, list) and target:
                    target = target[0]
                else:
                    return  # Skip if array is empty or not found
            else:
                target = target[step]
        target["junk_key_at_" + "_".join(path)] = "fail"

    # Build a full valid minimal config based on schema
    base_valid = build_valid_minimal(schema)

    # Identify all object paths
    all_paths = get_object_paths(schema)

    app_yaml = config_dir / "app.yaml"

    for path in all_paths:
        if "_items_" in path:
            continue  # Skipping array items for now to keep it simple

        # 1. Start clean
        test_data = json.loads(json.dumps(base_valid))  # Deep copy

        # 2. Inject junk at this specific level
        inject_junk(test_data, path)

        # 3. Write and test
        with open(app_yaml, "w") as f:
            yaml.dump(test_data, f)

        try:
            load_app_config()
            pytest.fail(f"Schema accepted additional property at level: {path or 'root'}")
        except ValidationError as e:
            # Success: junk was rejected
            assert "Additional properties are not allowed" in str(e)
            assert "junk_key_at" in str(e)
