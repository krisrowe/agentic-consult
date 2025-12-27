import os
import shutil
import pytest
import tempfile
import json
import time
import subprocess
import random
import string
from pathlib import Path
from click.testing import CliRunner
from datetime import datetime
import google.auth
from google.auth.exceptions import DefaultCredentialsError

# Import the CLI entry points
from agentic_consult.cli.backup import backup as backup_cli
from agentic_consult.cli.config import config_set
from agentic_consult.config import load_main_config
from agentic_consult.backup.drive import DriveClient

# Helper to generate random strings
def random_str(k=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=k))

@pytest.fixture
def integration_env(monkeypatch):
    """
    Sets up a complete isolated environment for integration testing.
    Uses BACKUPS_HOME_LOCAL_PATH to isolate 'user home' files without
    breaking Google Auth (which depends on real HOME).
    """
    # 1. Create a root temp directory for this test run
    root_temp = tempfile.mkdtemp(prefix="consult_integration_")
    
    # 2. Setup Mock HOME (for file content)
    # We DO NOT mock 'HOME' env var, but point our tool to this dir
    mock_home_dir = os.path.join(root_temp, "mock_home")
    os.makedirs(mock_home_dir)
    monkeypatch.setenv("BACKUPS_HOME_LOCAL_PATH", mock_home_dir)
    
    # 3. Setup CONSULT_CONFIG_DIR (for tool settings isolation)
    config_dir = os.path.join(root_temp, "config")
    os.makedirs(config_dir)
    monkeypatch.setenv("CONSULT_CONFIG_DIR", config_dir)
    
    # 4. Setup Workspace (~/ws)
    # Since we are using BACKUPS_HOME_LOCAL_PATH, we can put ws anywhere,
    # but let's put it inside mock_home for consistency with 'local repos' expectation
    # or just separate.
    # The tool now requires explicit configuration for local repos, so we can put it anywhere.
    ws_dir = os.path.join(root_temp, "ws")
    os.makedirs(ws_dir)
    
    yield {
        "root": root_temp,
        "home": mock_home_dir,
        "config": config_dir,
        "ws": ws_dir
    }
    
    # Cleanup
    if os.path.exists(root_temp):
        shutil.rmtree(root_temp)

def setup_git_repo(path, dirty=False):
    """Creates a git repo at path. If dirty=True, leaves uncommitted changes."""
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True, capture_output=True)
    
    readme = os.path.join(path, "README.md")
    with open(readme, "w") as f:
        f.write("# Initial Content")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=path, check=True, capture_output=True)
    
    if dirty:
        with open(readme, "a") as f:
            f.write("\nDirty changes")

@pytest.mark.integration
def test_backup_lifecycle_end_to_end(integration_env):
    """
    Full end-to-end integration test for the backup lifecycle.
    """
    env = integration_env
    runner = CliRunner()
    
    try:
        drive_client = DriveClient()
    except DefaultCredentialsError:
        pytest.skip("Skipping integration test: Google Cloud credentials not found.")
    
    # --- Setup: User Home Config Files ---
    gemini_dir = os.path.join(env['home'], ".gemini")
    os.makedirs(gemini_dir)
    
    gemini_content = f"Random content: {random_str(20)}"
    with open(os.path.join(gemini_dir, "GEMINI.md"), "w") as f:
        f.write(gemini_content)
    with open(os.path.join(gemini_dir, "settings.json"), "w") as f:
        f.write('{"test_setting": true}')

    # --- Setup: Repositories ---
    repo1 = os.path.join(env['ws'], "clean_repo_1")
    repo2 = os.path.join(env['ws'], "clean_repo_2")
    repo3 = os.path.join(env['ws'], "dirty_repo")
    
    setup_git_repo(repo1)
    setup_git_repo(repo2)
    setup_git_repo(repo3, dirty=True)

    # --- Step 1: Verify No Config ---
    settings_path = os.path.join(env['config'], "settings.json")
    assert not os.path.exists(settings_path)

    # --- Step 2: Config Create Folder ---
    folder_name = f"Consult_Test_Backup_{random_str()}"
    print(f"\n[Test] Creating backup folder: {folder_name}")
    
    result = runner.invoke(backup_cli, ['config', '--folder-name', folder_name, '--create'])
    assert result.exit_code == 0
    
    config = load_main_config()
    folder_id = config.get('backups', {}).get('google_drive_folder_id')
    assert folder_id is not None
    
    # --- Step 2b: Configure Providers ---
    # 1. Local Repos Path
    result = runner.invoke(config_set, ['backups.local_repos.path', env['ws']])
    assert result.exit_code == 0
    
    # 2. User Home Paths (Using JSON manipulation as CLI support for lists is basic/absent)
    # We will just write to the config file for the list
    config = load_main_config()
    if 'user_home' not in config.get('backups', {}):
        if 'backups' not in config: config['backups'] = {}
        config['backups']['user_home'] = {}
    
    config['backups']['user_home']['paths'] = [
        ".gemini/settings.json",
        ".gemini/GEMINI.md"
    ]
    
    # We save directly
    with open(settings_path, 'w') as f:
        json.dump(config, f, indent=2)

    # --- Step 3: Verify Duplicate Creation Fails ---
    result = runner.invoke(backup_cli, ['config', '--folder-name', folder_name, '--create'])
    assert result.exit_code != 0

    # --- Step 4: Verify Re-config via ID ---
    # Save config content to restore later
    with open(settings_path, 'r') as f:
        full_config = json.load(f)
        
    os.remove(settings_path)
    
    # Config using ID
    result = runner.invoke(backup_cli, ['config', '--folder-id', folder_id])
    assert result.exit_code == 0
    
    # Restore the full config (paths etc)
    with open(settings_path, 'w') as f:
        json.dump(full_config, f, indent=2)

    # --- Step 5: Backup Execution (Run 1) ---
    print("\n[Test] Running first backup...")
    result = runner.invoke(backup_cli, ['run', '--non-interactive', '--skip-dirty', '--format', 'json'])
    assert result.exit_code == 0
    
    output_json = json.loads(result.stdout)
    
    gemini_res = next(r for r in output_json if r['provider_name'] == "User Home Configuration")
    local_res = next(r for r in output_json if r['provider_name'] == "Local-Only Git Repositories")
    
    assert gemini_res['status'] == 'success'
    assert len(gemini_res['items']) == 2
    
    assert local_res['status'] == 'success'
    repo_items = {item['name']: item for item in local_res['items']}
    
    assert repo_items['clean_repo_1']['status'] == 'Success'
    assert repo_items['dirty_repo']['status'] == 'Skipped'

    # --- Step 6: Verify Drive Content (Run 1) ---
    # Check User Home files
    home_folder_id = drive_client.find_folder("home", parent_id=folder_id)
    gemini_folder_id = drive_client.find_folder(".gemini", parent_id=home_folder_id)
    
    remote_gemini_md = drive_client.find_file("GEMINI.md", parent_id=gemini_folder_id)
    assert remote_gemini_md is not None

    # --- Step 7: Modify and Backup (Run 2) ---
    print("\n[Test] Modifying repo and running second backup...")
    
    with open(os.path.join(repo1, "new_file.txt"), "w") as f:
        f.write("New content")
    subprocess.run(["git", "add", "."], cwd=repo1, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Second commit"], cwd=repo1, check=True, capture_output=True)
    
    result = runner.invoke(backup_cli, ['run', '--non-interactive', '--skip-dirty', '--format', 'json'])
    assert result.exit_code == 0
    output_json_2 = json.loads(result.stdout)
    local_res_2 = next(r for r in output_json_2 if r['provider_name'] == "Local-Only Git Repositories")
    repo_items_2 = {item['name']: item for item in local_res_2['items']}
    
    assert repo_items_2['clean_repo_1']['status'] == 'Success'
    assert repo_items_2['clean_repo_2']['status'] == 'Skipped'

    # --- Cleanup ---
    try:
        drive_client.service.files().delete(fileId=folder_id).execute()
        print(f"\n[Test] Cleaned up Drive folder: {folder_id}")
    except Exception as e:
        print(f"Warning: Failed to cleanup Drive folder: {e}")
