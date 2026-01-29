import os
import subprocess
import textwrap
from pathlib import Path
import importlib.util
from pathlib import Path as _Path
import sys as _sys

# load tests/util/synthetic.py as a module at runtime so tests don't depend on
# package import machinery
_spec = importlib.util.spec_from_file_location(
    "tests_util_synthetic",
    str(_Path(__file__).resolve().parents[3] / 'util' / 'synthetic.py'),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
generate_synthetic_drive_id = _mod.generate_synthetic_drive_id

def run_checker(repo_root, tmp_repo_dir, customers_dir, expect_ok=True, args=None):
    # Use sys.executable to run our module directly
    # Use --only=customers to skip slow checks like devws
    cmd = [_sys.executable, '-m', 'agentic_consult', 'precommit', '--only=customers', str(tmp_repo_dir)]
    if args:
        cmd.extend(args)
        
    env = os.environ.copy()
    # Ensure local module is found
    env['PYTHONPATH'] = f"{repo_root}:{env.get('PYTHONPATH', '')}"
    env['CUSTOMERS_DIR'] = str(customers_dir)
    # point git to the temp repo so the checker inspects that index
    env['GIT_DIR'] = str(Path(tmp_repo_dir) / '.git')
    env['GIT_WORK_TREE'] = str(tmp_repo_dir)
    
    # Add .gitignore to ignore customers dir
    with open(tmp_repo_dir / '.gitignore', 'a') as f:
        f.write('customers/\n')
    
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
    assert 'checks passed' in out


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
    assert 'GenericBank' in out


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

    # Validate match detected
    assert 'specialword' in out
    assert 'Customer patterns' in out


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

    out = run_checker(repo_root, tmp, customers, expect_ok=False)

    # Verify sentinel matches detected
    assert 'sentinel' in out
    assert 'Customer patterns' in out


def test_precommit_respects_gitignore(tmp_path):
    """Verify precommit skips gitignored files by default."""
    repo_root = Path.cwd()
    tmp_repo = tmp_path / 'test_repo'
    tmp_repo.mkdir()
    tmp_customers = tmp_path / 'customers_config'
    tmp_customers.mkdir()
    subprocess.run(['git', 'init', str(tmp_repo)], check=True)

    (tmp_customers / 'ignoretest').mkdir(parents=True)
    cust_yaml = tmp_customers / 'ignoretest' / 'customer.yaml'
    cust_yaml.write_text(textwrap.dedent('''
        name: IgnoreTest
        slug: ignoretest
        drive_folder_id: 'IGNORE789'
        keywords: [secretword]
    '''))

    gitignore = tmp_repo / '.gitignore'
    gitignore.write_text('*.log\n')
    subprocess.run(['git', '-C', str(tmp_repo), 'add', str(gitignore)], check=True)

    log_file = tmp_repo / 'app.log'
    log_file.write_text('Log entry: secretword')

    out = run_checker(repo_root, tmp_repo, tmp_customers, expect_ok=True)
    assert 'checks passed' in out


def test_exit_code_zero_on_all_passing(tmp_path):
    """Explicitly verify exit code 0 when everything passes."""
    repo_root = Path.cwd()
    tmp = tmp_path / 'repo_success'
    tmp.mkdir()
    subprocess.run(['git', 'init', str(tmp)], check=True)
    customers = tmp / 'customers'
    customers.mkdir()

    out = run_checker(repo_root, tmp, customers, expect_ok=True)
    assert 'checks passed' in out


def test_exit_code_not_zero_on_single_failure(tmp_path):
    """Explicitly verify non-zero exit code when one check fails."""
    repo_root = Path.cwd()
    tmp = tmp_path / 'repo_fail_1'
    tmp.mkdir()
    subprocess.run(['git', 'init', str(tmp)], check=True)
    
    customers = tmp / 'customers'
    (customers / 'failcorp').mkdir(parents=True)
    (customers / 'failcorp' / 'customer.yaml').write_text("name: FailCorp\nslug: failcorp\nkeywords: [badword]")

    f = tmp / 'file.txt'
    f.write_text('this has a badword')
    subprocess.run(['git', '-C', str(tmp), 'add', str(f)], check=True)

    out = run_checker(repo_root, tmp, customers, expect_ok=False)
    assert 'FAILED' in out


def test_exit_code_not_zero_on_multiple_failures(tmp_path):
    """Explicitly verify non-zero exit code when multiple checks fail."""
    repo_root = Path.cwd()
    tmp = tmp_path / 'repo_fail_multi'
    tmp.mkdir()
    subprocess.run(['git', 'init', str(tmp)], check=True)
    
    customers = tmp / 'customers'
    (customers / 'failcorp').mkdir(parents=True)
    (customers / 'failcorp' / 'customer.yaml').write_text("name: FailCorp\nslug: failcorp\nkeywords: [badword]")

    # Keyword failure
    f1 = tmp / 'file1.txt'
    f1.write_text('badword')
    subprocess.run(['git', '-C', str(tmp), 'add', str(f1)], check=True)

    out = run_checker(repo_root, tmp, customers, expect_ok=False)
    assert 'FAILED' in out
    assert 'badword' in out or 'Customer' in out