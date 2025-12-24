import os
import subprocess
import textwrap
from pathlib import Path
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


import sys as _sys

def run_checker(repo_root, tmp_repo_dir, customers_dir, expect_ok=True):
    # Use sys.executable to run our module directly
    cmd = [_sys.executable, '-m', 'agentic_consult', 'precommit', str(tmp_repo_dir)]
    env = os.environ.copy()
    # Ensure local module is found
    env['PYTHONPATH'] = f"{repo_root}:{env.get('PYTHONPATH', '')}"
    env['CUSTOMERS_DIR'] = str(customers_dir)
    # point git to the temp repo so the checker inspects that index
    env['GIT_DIR'] = str(Path(tmp_repo_dir) / '.git')
    env['GIT_WORK_TREE'] = str(tmp_repo_dir)
    
    # Add .gitignore to ignore customers dir
    (tmp_repo_dir / '.gitignore').write_text('customers/\n')
    
    proc = subprocess.run(cmd, cwd=repo_root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    output = proc.stdout
    if expect_ok:
        assert proc.returncode == 0, f"expected success but exit {proc.returncode}\n{output}"
    else:
        assert proc.returncode != 0, f"expected failure but exit 0\n{output}"
    return output


def test_precommit_no_matches(tmp_path):
    repo_root = Path.cwd()
    # setup a temp git repo
    tmp = tmp_path / 'repo'
    tmp.mkdir()
    subprocess.run(['git', 'init', str(tmp)], check=True)

    # create customers dir with a customer but no files referencing it
    customers = tmp / 'customers'
    (customers / 'fakecorp').mkdir(parents=True)
    cust_yaml = customers / 'fakecorp' / 'customer.yaml'
    cust_yaml.write_text(textwrap.dedent('''
        name: FakeCorp
        slug: fakecorp
        drive_folder_id: 'DRIVE123'
        keywords:
          - fakecorp
    '''))

    # create a benign file and stage it
    f = tmp / 'notes.txt'
    f.write_text('this is a totally safe note')
    subprocess.run(['git', '-C', str(tmp), 'add', str(f)], check=True)

    out = run_checker(repo_root, tmp, customers, expect_ok=True)
    assert 'No sensitive matches found' in out


def test_precommit_detects_match(tmp_path):


    repo_root = Path.cwd()


    tmp = tmp_path / 'repo2'


    tmp.mkdir()


    subprocess.run(['git', 'init', str(tmp)], check=True)





    # customers dir with a customer


    customers = tmp / 'customers'


    (customers / 'genericbank').mkdir(parents=True)


    cust_yaml = customers / 'genericbank' / 'customer.yaml'


    token = generate_synthetic_drive_id()


    cust_yaml.write_text(textwrap.dedent(f'''


        name: GenericBank


        slug: genericbank


        drive_folder_id: '{token}'


        keywords:


          - GenericBank


    '''))





    # create a file that contains the customer's name


    f = tmp / 'inbound.txt'


    f.write_text('I received an email from GenericBank about my account')


    subprocess.run(['git', '-C', str(tmp), 'add', str(f)], check=True)





    out = run_checker(repo_root, tmp, customers, expect_ok=False)


    # should report the matched literal and type


    assert 'type=name' in out or 'type=keyword' in out or 'GenericBank' in out


def test_precommit_reports_exact_line_and_value(tmp_path):
    """Verify precommit reports exact file name, line number, and matched value."""
    repo_root = Path.cwd()
    tmp = tmp_path / 'repo_exact'
    tmp.mkdir()
    subprocess.run(['git', 'init', str(tmp)], check=True)

    customers = tmp / 'customers'
    (customers / 'testco').mkdir(parents=True)
    cust_yaml = customers / 'testco' / 'customer.yaml'
    cust_yaml.write_text(textwrap.dedent('''
        name: TestCompany
        slug: testco
        drive_folder_id: 'TESTDRIVE999'
        keywords:
          - testco
          - specialword
    '''))

    # Create a file with "specialword" on line 3
    f = tmp / 'data.txt'
    f.write_text('Line 1: safe content\nLine 2: more safe stuff\nLine 3: found specialword here\nLine 4: clean')
    subprocess.run(['git', '-C', str(tmp), 'add', str(f)], check=True)

    out = run_checker(repo_root, tmp, customers, expect_ok=False)
    
    # Validate exact match details
    assert 'data.txt' in out
    assert 'Line 3:' in out
    assert 'specialword' in out


def test_precommit_counts_multiple_matches_accurately(tmp_path):
    """Verify precommit correctly counts multiple matches on non-adjacent lines."""
    repo_root = Path.cwd()
    tmp = tmp_path / 'repo_multi'
    tmp.mkdir()
    subprocess.run(['git', 'init', str(tmp)], check=True)

    customers = tmp / 'customers'
    (customers / 'multitest').mkdir(parents=True)
    cust_yaml = customers / 'multitest' / 'customer.yaml'
    cust_yaml.write_text(textwrap.dedent('''
        name: MultiTest
        slug: multitest
        drive_folder_id: 'MULTI123'
        keywords:
          - sentinel
    '''))

    # Create file1 with two matches on non-adjacent lines (lines 2 and 5)
    file1 = tmp / 'file1.txt'
    file1.write_text('Line 1\nLine 2 has sentinel value\nLine 3\nLine 4\nLine 5 also has sentinel\nLine 6')
    subprocess.run(['git', '-C', str(tmp), 'add', str(file1)], check=True)

    # Create file2 with no matches
    file2 = tmp / 'file2.txt'
    file2.write_text('Totally clean file\nNo issues here')
    subprocess.run(['git', '-C', str(tmp), 'add', str(file2)], check=True)

    out = run_checker(repo_root, tmp, customers, expect_ok=False)
    
    # Verify file1 has exactly 2 matches on lines 2 and 5
    assert 'file1.txt' in out
    assert 'Line 2:' in out
    assert 'Line 5:' in out
    
    # Verify file2 is not mentioned (no matches)
    assert 'file2.txt' not in out
    
    # Count occurrences of 'sentinel' in output (should be at least 2 for the two match reports)
    sentinel_count = out.count('sentinel')
    assert sentinel_count >= 2, f"Expected at least 2 'sentinel' mentions, found {sentinel_count}"


def test_precommit_respects_gitignore(tmp_path):
    """Verify precommit skips gitignored files by default, includes them with --include-ignored."""
    repo_root = Path.cwd()
    
    # Separate directories: one for the repo, one for customers config
    tmp_repo = tmp_path / 'test_repo'
    tmp_repo.mkdir()
    tmp_customers = tmp_path / 'customers_config'
    tmp_customers.mkdir()
    
    subprocess.run(['git', 'init', str(tmp_repo)], check=True)

    # Customers config in separate directory (not part of the scanned repo)
    (tmp_customers / 'ignoretest').mkdir(parents=True)
    cust_yaml = tmp_customers / 'ignoretest' / 'customer.yaml'
    cust_yaml.write_text(textwrap.dedent('''
        name: IgnoreTest
        slug: ignoretest
        drive_folder_id: 'IGNORE789'
        keywords:
          - secretword
    '''))

    # Create gitignore file in the repo
    gitignore = tmp_repo / '.gitignore'
    gitignore.write_text('*.log\n')
    subprocess.run(['git', '-C', str(tmp_repo), 'add', str(gitignore)], check=True)

    # Create a tracked file with no sensitive data
    clean_file = tmp_repo / 'clean.txt'
    clean_file.write_text('This file is totally clean')
    subprocess.run(['git', '-C', str(tmp_repo), 'add', str(clean_file)], check=True)

    # Create a gitignored log file with sensitive keyword
    log_file = tmp_repo / 'app.log'
    log_file.write_text('Log entry: processed secretword successfully')

    # Run without --include-ignored (should pass - gitignored file not scanned)
    cmd_default = [_sys.executable, '-m', 'agentic_consult', 'precommit']
    env = os.environ.copy()
    env['PYTHONPATH'] = f"{repo_root}:{env.get('PYTHONPATH', '')}"
    env['CUSTOMERS_DIR'] = str(tmp_customers)
    env['GIT_DIR'] = str(tmp_repo / '.git')
    env['GIT_WORK_TREE'] = str(tmp_repo)
    proc_default = subprocess.run(cmd_default, cwd=str(tmp_repo), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    
    assert proc_default.returncode == 0, f"Expected pass without --include-ignored, got exit {proc_default.returncode}\n{proc_default.stdout}"
    assert 'app.log' not in proc_default.stdout, "Gitignored file should not be scanned by default"

    # Run with --include-ignored (should fail - gitignored file scanned)
    cmd_include = [_sys.executable, '-m', 'agentic_consult', 'precommit', '--include-ignored']
    proc_include = subprocess.run(cmd_include, cwd=str(tmp_repo), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    
    assert proc_include.returncode != 0, f"Expected failure with --include-ignored, got exit {proc_include.returncode}\n{proc_include.stdout}"
    assert 'app.log' in proc_include.stdout, "Gitignored file should be detected with --include-ignored"
    assert 'secretword' in proc_include.stdout, "Should find the sensitive keyword in gitignored file"



