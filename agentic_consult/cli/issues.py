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
    from agentic_consult.sdk.issues import list_issues
    # from agentic_consult.ticktick import load_tasks_from_json
    
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
        
        # Get open task count (Mocked/Disabled for now)
        task_count = "?" 
        
        # Get issues via SDK
        issues = list_issues(c_slug, status='all')
        open_issues = [i for i in issues if i['status'] == 'open']
        resolved_issues = [i for i in issues if i['status'] == 'resolved']
            
        if verbose:
            click.echo(f"\n=== {c_name} ({task_count} Open Tasks) ===")
            if not open_issues:
                click.echo("  No open issues found.")
            
            for issue in open_issues:
                click.echo(f"  [OPEN] {issue['name']}")
                _print_preview(issue['path'])
            
            if resolved_issues:
                click.echo(f"\n  [RESOLVED] {len(resolved_issues)} issues archived.")
        else:
            click.echo(f"{c_name:<20} | Tasks: {task_count:<3} | Open Issues: {len(open_issues):<3} (Resolved: {len(resolved_issues)})")

def _print_preview(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            preview = content[:100].replace('\n', ' ')
            if len(content) > 100: preview += "..."
            click.echo(f"    Preview: {preview}")
    except Exception:
        click.echo("    (Could not read content)")
