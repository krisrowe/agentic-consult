import os
import subprocess
import textwrap
from pathlib import Path


import sys as _sys

def run_checker(repo_root, tmp_repo_dir, customers_dir, expect_ok=True):
    # Use sys.executable to run our module directly
    cmd = [_sys.executable, '-m', 'agentic_consult', 'precommit']
    env = os.environ.copy()
    # Ensure local module is found
    env['PYTHONPATH'] = f"{repo_root}:{env.get('PYTHONPATH', '')}"
    env['CUSTOMERS_DIR'] = str(customers_dir)
    env['GIT_DIR'] = str(Path(tmp_repo_dir) / '.git')
    env['GIT_WORK_TREE'] = str(tmp_repo_dir)
    proc = subprocess.run(cmd, cwd=repo_root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    output = proc.stdout
    if expect_ok:
        assert proc.returncode == 0, f"expected success but exit {proc.returncode}\n{output}"
    else:
        assert proc.returncode != 0, f"expected failure but exit 0\n{output}"
    return output


def test_variable_name_alone_does_not_trigger(tmp_path):
    repo_root = Path.cwd()
    tmp = tmp_path / 'repo_var'
    tmp.mkdir()
    subprocess.run(['git', 'init', str(tmp)], check=True)

    customers = tmp / 'customers'
    (customers / 'fakecorp').mkdir(parents=True)
    cust_yaml = customers / 'fakecorp' / 'customer.yaml'
    cust_yaml.write_text(textwrap.dedent('''
        name: FakeCorp
        slug: fakecorp
        # note: no drive id provided
    '''))

    f = tmp / 'config.txt'
    # include the variable name but no value on same line
    f.write_text('some config\ndrive_folder_id:\nend')
    subprocess.run(['git', '-C', str(tmp), 'add', str(f)], check=True)

    out = run_checker(repo_root, tmp, customers, expect_ok=True)
    assert 'Drive' not in out


def test_long_non_id_token_not_matched(tmp_path):
    repo_root = Path.cwd()
    tmp = tmp_path / 'repo_long'
    tmp.mkdir()
    subprocess.run(['git', 'init', str(tmp)], check=True)

    customers = tmp / 'customers'
    (customers / 'fakecorp').mkdir(parents=True)
    cust_yaml = customers / 'fakecorp' / 'customer.yaml'
    cust_yaml.write_text(textwrap.dedent('''
        name: FakeCorp
        slug: fakecorp
    '''))

    f = tmp / 'notes.md'
    # a long identifier-like token but no digits
    f.write_text('this is a label: completed_ticktick_tasks_should_not_match')
    subprocess.run(['git', '-C', str(tmp), 'add', str(f)], check=True)

    out = run_checker(repo_root, tmp, customers, expect_ok=True)
    assert 'detected Drive-like id value' not in out


import importlib.util
from pathlib import Path as _Path

# load tests/util/synthetic.py as a module at runtime so tests don't depend on
# package import machinery
_spec = importlib.util.spec_from_file_location(
    "tests_util_synthetic",
    str(_Path(__file__).resolve().parents[1] / 'util' / 'synthetic.py'),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
generate_synthetic_drive_id = _mod.generate_synthetic_drive_id


def test_real_drive_id_detected(tmp_path):
    repo_root = Path.cwd()
    tmp = tmp_path / 'repo_id'
    tmp.mkdir()
    subprocess.run(['git', 'init', str(tmp)], check=True)

    customers = tmp / 'customers'
    (customers / 'bank').mkdir(parents=True)
    cust_yaml = customers / 'bank' / 'customer.yaml'
    token = generate_synthetic_drive_id()
    cust_yaml.write_text(textwrap.dedent(f'''
        name: Bank
        slug: bank
        drive_folder_id: '{token}'
    '''))

    f = tmp / 'found.txt'
    f.write_text(f'here is a drive id: {token}')
    subprocess.run(['git', '-C', str(tmp), 'add', str(f)], check=True)

    out = run_checker(repo_root, tmp, customers, expect_ok=False)
    assert token in out
