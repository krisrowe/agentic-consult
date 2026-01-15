"""Test that terraform configuration is valid.

Tests terraform HCL syntax and structure. Variable validation happens at
plan/apply time, not validate time, so these tests focus on what validate
actually checks.

Catches: bad HCL syntax, invalid references, type mismatches, malformed blocks.
Does NOT check: whether GCP resources exist, or whether variables have values.

For the CLI/Terraform decoupling design (why we use -var flags instead of
external data sources), see deploy/DESIGN.md#cliterraform-decoupling.
"""
import subprocess
from pathlib import Path

import pytest


TF_DIR = Path(__file__).parent.parent.parent / "deploy" / "terraform"


@pytest.fixture(scope="module")
def tf_init():
    """Run terraform init once for all tests in this module."""
    result = subprocess.run(
        ["terraform", "init", "-backend=false", "-input=false"],
        cwd=TF_DIR,
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"terraform init failed:\n{result.stderr}"


def test_terraform_hcl_is_valid(tf_init):
    """Terraform validates HCL syntax and structure.

    This tests that:
    - All .tf files have valid HCL syntax
    - All resource references are valid (no typos in resource names)
    - All variable types match their usage
    - All required provider/resource arguments are present

    Note: terraform validate does NOT check variable values. Variables
    are validated at plan/apply time. The CLI's pre-deploy command
    ensures variables are provided via -var flags.
    """
    result = subprocess.run(
        ["terraform", "validate"],
        cwd=TF_DIR,
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"terraform validate failed:\n{result.stderr}"


def test_terraform_has_required_variable_declarations(tf_init):
    """Terraform config declares the required input variables.

    This ensures the main.tf declares project_id and bucket_name as
    input variables. The CLI's pre-deploy command provides these via
    -var flags at apply time.
    """
    main_tf = TF_DIR / "main.tf"
    content = main_tf.read_text()

    # Check that variable blocks exist for required inputs
    assert 'variable "project_id"' in content, "Missing project_id variable declaration"
    assert 'variable "bucket_name"' in content, "Missing bucket_name variable declaration"

    # Check that these are marked as required (no default value)
    # A variable without a default is required
    import re

    # Match variable block and check it doesn't have a default
    project_var = re.search(r'variable "project_id" \{[^}]+\}', content)
    assert project_var, "Could not find project_id variable block"
    assert "default" not in project_var.group(), "project_id should be required (no default)"

    bucket_var = re.search(r'variable "bucket_name" \{[^}]+\}', content)
    assert bucket_var, "Could not find bucket_name variable block"
    assert "default" not in bucket_var.group(), "bucket_name should be required (no default)"
