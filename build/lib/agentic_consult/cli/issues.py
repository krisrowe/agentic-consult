import click
import sys

from agentic_consult.customers import find_customer_by_id, get_active_customers_root, _parse_customer_yaml

@click.group()
def issues():
    """Manage customer issues."""
    pass

@issues.command(name='list')
@click.argument('identifier', required=False)
@click.option('--verbose', '-v', is_flag=True, help="Show issue details and previews.")
def issues_list(identifier, verbose):
    """List issues and open task counts for customers."""
    from agentic_consult.ticktick import load_tasks_from_json
    
    root = get_active_customers_root()
    if not root.exists():
        click.echo("No customers found.")
        return

    customers = []
    if identifier:
        cust = find_customer_by_id(identifier)
        if not cust:
            click.echo(f"Customer '{identifier}' not found.", err=True)
            sys.exit(1)
        customers.append(cust)
    else:
        # Load all customers
        for d in root.iterdir():
            if d.is_dir():
                c_yaml = d / "customer.yaml"
                if c_yaml.exists():
                    customers.append(_parse_customer_yaml(c_yaml))
    
    if not customers:
        click.echo("No customers found.")
        return

    for cust in customers:
        c_slug = cust['slug']
        c_name = cust['name']
        cust_dir = root / c_slug
        
        # Get open task count from cache
        tasks_dir = cust_dir / 'tasks'
        tasks = load_tasks_from_json(tasks_dir)
        task_count = len(tasks)
        
        # Get issues
        issues_dir = cust_dir / 'issues'
        issues = []
        if issues_dir.exists():
            issues = [f for f in issues_dir.iterdir() if f.is_file() and not f.name.startswith('.')]
            # Sort by modification time, newest first
            issues.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            
        if verbose:
            click.echo(f"\n=== {c_name} ({task_count} Open Tasks) ===")
            if not issues:
                click.echo("  No issues found.")
            for issue in issues:
                click.echo(f"  [Issue] {issue.name}")
                try:
                    with open(issue, 'r', encoding='utf-8') as f:
                        content = f.read()
                        preview = content[:100].replace('\n', ' ')
                        if len(content) > 100: preview += "..."
                        click.echo(f"    Preview: {preview}")
                except Exception:
                    click.echo("    (Could not read content)")
        else:
            # Table row format
            issue_names = ", ".join([i.name for i in issues]) if issues else "-"
            click.echo(f"{c_name:<20} | Tasks: {task_count:<3} | Issues: {issue_names}")
