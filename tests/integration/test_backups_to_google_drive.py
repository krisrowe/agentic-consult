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
from agentic_consult.cli.user_home import init_defaults as user_home_init_defaults
from agentic_consult.config import load_main_config
from agentic_consult.backup.drive import DriveClient
from agentic_consult.backup.results import BackupStatus

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
    # Move it INSIDE mock home to simulate standard XDG layout (~/.config/agentic-consult)
    config_dir = os.path.join(mock_home_dir, ".config", "agentic-consult")
    os.makedirs(config_dir)
    monkeypatch.setenv("CONSULT_CONFIG_DIR", config_dir)
    
    # 4. Setup Workspace (~/ws)
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
    """
    Creates a git repo at path.
    If dirty=True, leaves uncommitted changes.
    """
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True, capture_output=True)
    
    # Initial commit
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
    
    # --- Setup: User Home Config Files (in mock_home_dir) ---
    # These are the files UserHomeBackup will look for in its 'home_dir'
    mock_gemini_dir = os.path.join(env['home'], ".gemini")
    os.makedirs(mock_gemini_dir)
    
    gemini_content = f"Random content: {random_str(20)}"
    with open(os.path.join(mock_gemini_dir, "GEMINI.md"), "w") as f:
        f.write(gemini_content)
    with open(os.path.join(mock_gemini_dir, "settings.json"), "w") as f:
        f.write('{"test_setting": true}')

    # --- Setup: Recursive Directory Content ---
    mock_subdir = os.path.join(mock_gemini_dir, "backup_assets")
    os.makedirs(mock_subdir)
    with open(os.path.join(mock_subdir, "file_a.txt"), "w") as f:
        f.write("Content A")
    with open(os.path.join(mock_subdir, "file_b.toml"), "w") as f:
        f.write("key = 'value'")
    
    # Nested subdir
    mock_nested = os.path.join(mock_subdir, "nested")
    os.makedirs(mock_nested)
    with open(os.path.join(mock_nested, "deep_file.json"), "w") as f:
        f.write("{}")

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

    # --- Step 2: Config Create Drive Folder ---
    folder_name = f"Consult_Test_Backup_{random_str()}"
    print(f"\n[Test] Creating Drive backup folder: {folder_name}")
    
    result = runner.invoke(backup_cli, ['config', '--folder-name', folder_name, '--create'])
    assert result.exit_code == 0
    
    config = load_main_config()
    folder_id = config.get('backups', {}).get('google_drive_folder_id')
    assert folder_id is not None
    
    # --- Step 2b: Configure Local Repos Path ---
    print("[Test] Configuring local repos path...")
    result = runner.invoke(config_set, ['backups.local_repos.path', env['ws']])
    assert result.exit_code == 0
    
    # Verify config updated
    config = load_main_config()
    assert config['backups']['local_repos']['path'] == env['ws']

    # --- Step 2c: Configure User Home Paths ---
    print("[Test] Initializing default user home paths...")
    result = runner.invoke(user_home_init_defaults)
    assert result.exit_code == 0
    
    from agentic_consult.cli.user_home import add_path
    
    # Add our recursive directory to the config using the proper CLI command
    # We invoke 'user-home add' which is now nested under 'backup'
    
    print("[Test] Adding recursive test dir to backup config...")
    result = runner.invoke(backup_cli, ['user-home', 'add', '.gemini/backup_assets'])
    assert result.exit_code == 0
    
    # Verify config updated
    config = load_main_config()
    current_paths = config['backups']['user_home']['paths']
    assert ".gemini/backup_assets" in current_paths

    # --- Step 3: Verify Duplicate Creation Fails ---
    print("\n[Test] Verifying duplicate folder creation fails...")
    result = runner.invoke(backup_cli, ['config', '--folder-name', folder_name, '--create'])
    assert result.exit_code != 0
    assert "already exists" in result.output

    # --- Step 4: Verify Re-config via ID ---
    print("\n[Test] Verifying re-configuration via ID...")
    # Save config content to restore later
    with open(settings_path, 'r') as f:
        full_config = json.load(f)
        
    os.remove(settings_path)
    assert not os.path.exists(settings_path)
    
    # Config using ID (restores only the ID, we'll restore user_home paths manually)
    result = runner.invoke(backup_cli, ['config', '--folder-id', folder_id])
    assert result.exit_code == 0
    
    # Restore the full config for subsequent backup runs
    with open(settings_path, 'w') as f:
        json.dump(full_config, f, indent=2)

    # --- Step 5: Backup Execution (Run 1) ---
    print("\n[Test] Running first backup...")
    result = runner.invoke(backup_cli, ['all', '--non-interactive', '--skip-dirty', '--format', 'json'])
    assert result.exit_code == 0
    
    output_json = json.loads(result.stdout)
    
    user_home_res = next(r for r in output_json if r['provider_name'] == "User Home Configuration")
    local_repos_res = next(r for r in output_json if r['provider_name'] == "Local-Only Git Repositories")
    
    # User Home Checks
    assert user_home_res['status'] == 'success'
    # We expect: 
    # 1. .gemini/settings.json (success)
    # 2. .gemini/GEMINI.md (success or not found if init defaults didn't create it, but our test setup did)
    # 3. .config/.../settings.json (success)
    # 4. .gemini/backup_assets/ (success - directory summary)
    
    # Check for the directory summary item
    dir_item = next((i for i in user_home_res['items'] if "backup_assets" in i['name']), None)
    assert dir_item is not None
    assert dir_item['status'] == BackupStatus.SUCCESS.value
    assert "Synced dir" in dir_item['message']
    
    # Local Repo Checks
    assert local_repos_res['status'] == 'success'
    repo_items = {item['name']: item for item in local_repos_res['items']}
    
    assert repo_items['clean_repo_1']['status'] == BackupStatus.SUCCESS.value
    assert repo_items['clean_repo_2']['status'] == BackupStatus.SUCCESS.value
    assert repo_items['dirty_repo']['status'] == BackupStatus.DIRTY.value
    assert "dirty" in repo_items['dirty_repo']['message'].lower()

    # --- Step 6: Verify Drive Content (Run 1) ---
    print("\n[Test] Verifying Drive content after first backup...")
    
    # Check User Home files
    home_folder_id = drive_client.find_folder("home", parent_id=folder_id)
    assert home_folder_id
    
    gemini_folder_id = drive_client.find_folder(".gemini", parent_id=home_folder_id)
    assert gemini_folder_id
    
    # Verify Recursive Directory
    recursive_dir_id = drive_client.find_folder("backup_assets", parent_id=gemini_folder_id)
    assert recursive_dir_id is not None
    
    file_a = drive_client.find_file("file_a.txt", parent_id=recursive_dir_id)
    assert file_a is not None
    
    file_b = drive_client.find_file("file_b.toml", parent_id=recursive_dir_id)
    assert file_b is not None
    
    nested_dir_id = drive_client.find_folder("nested", parent_id=recursive_dir_id)
    assert nested_dir_id is not None
    
    deep_file = drive_client.find_file("deep_file.json", parent_id=nested_dir_id)
    assert deep_file is not None

    remote_gemini_md = drive_client.find_file("GEMINI.md", parent_id=gemini_folder_id)
    assert remote_gemini_md is not None
    assert remote_gemini_md['name'] == "GEMINI.md"

    remote_gemini_settings = drive_client.find_file("settings.json", parent_id=gemini_folder_id)
    assert remote_gemini_settings is not None
    assert remote_gemini_settings['name'] == "settings.json"

    # Check agentic-consult settings.json backup
    config_agentic_folder_id = drive_client.find_folder(".config", parent_id=home_folder_id)
    assert config_agentic_folder_id
    config_consult_folder_id = drive_client.find_folder("agentic-consult", parent_id=config_agentic_folder_id)
    assert config_consult_folder_id

    remote_consult_settings = drive_client.find_file("settings.json", parent_id=config_consult_folder_id)
    assert remote_consult_settings is not None
    assert remote_consult_settings['name'] == "settings.json"

    # Check Local Repo bundles
    local_repos_folder_id = drive_client.find_folder("local-only-repos", parent_id=folder_id)
    assert local_repos_folder_id
    
    bundle1 = drive_client.find_file("clean_repo_1.bundle", parent_id=local_repos_folder_id)
    bundle2 = drive_client.find_file("clean_repo_2.bundle", parent_id=local_repos_folder_id)
    bundle3 = drive_client.find_file("dirty_repo.bundle", parent_id=local_repos_folder_id)
    
    assert bundle1 is not None
    assert bundle2 is not None
    assert bundle3 is None # Should NOT be there

    bundle1_id_initial = bundle1['id']
    bundle1_modified_initial = drive_client.find_file_by_id(bundle1_id_initial).get('modifiedTime')
    bundle1_created_initial = drive_client.find_file_by_id(bundle1_id_initial).get('createdTime')

    # --- Step 7: Modify and Backup (Run 2) ---
    print("\n[Test] Modifying repo and running second backup...")
    
    # Modify repo1
    time.sleep(1) # Ensure modified time changes
    with open(os.path.join(repo1, "another_file.txt"), "w") as f:
        f.write("More new content")
    subprocess.run(["git", "add", "."], cwd=repo1, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Third commit (modified repo1)"], cwd=repo1, check=True, capture_output=True)
    
    # Dirty repo3 again
    with open(os.path.join(repo3, "dirty_file_2.txt"), "w") as f:
        f.write("Even more dirty content")

    result = runner.invoke(backup_cli, ['all', '--non-interactive', '--skip-dirty', '--format', 'json'])
    assert result.exit_code == 0
    output_json_2 = json.loads(result.stdout)
    local_repos_res_2 = next(r for r in output_json_2 if r['provider_name'] == "Local-Only Git Repositories")
    repo_items_2 = {item['name']: item for item in local_repos_res_2['items']}
    
    # Verify statuses
    assert repo_items_2['clean_repo_1']['status'] == BackupStatus.SUCCESS.value # Updated
    assert "Updated" in repo_items_2['clean_repo_1']['message']
    assert repo_items_2['clean_repo_2']['status'] == BackupStatus.NO_CHANGE.value # Still unchanged
    assert "No new commits" in repo_items_2['clean_repo_2']['message']
    
    assert repo_items_2['dirty_repo']['status'] == BackupStatus.DIRTY.value # Skipped dirty

    # --- Step 8: Verify Drive Updates (Run 2) ---
    print("\n[Test] Verifying Drive updates after second backup...")
    bundle1_final = drive_client.find_file_by_id(bundle1_id_initial)
    
    assert bundle1_final['id'] == bundle1_id_initial
    assert bundle1_final['modifiedTime'] > bundle1_modified_initial
    assert bundle1_final['createdTime'] == bundle1_created_initial

    # Verify file history (if API supports, and if fields are requested)
    # The Drive API v3 `files.get` with `fields='id,name,revisions'` could show this.
    # But our client doesn't expose revisions directly.
    # We rely on modifiedTime > initial_modified_time and same ID.
    print(f"Verified that 'clean_repo_1.bundle' was updated (ID: {bundle1_final['id']}).")

    # --- Cleanup ---
    try:
        drive_client.service.files().delete(fileId=folder_id).execute()
        print(f"\n[Test] Cleaned up Drive folder: {folder_id}")
    except Exception as e:
        print(f"Warning: Failed to cleanup Drive folder: {e}")