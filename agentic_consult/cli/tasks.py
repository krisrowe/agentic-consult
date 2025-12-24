import click
import sys

from agentic_consult.customers import find_customer_by_id, get_active_customers_root, _parse_customer_yaml

@click.group()
def tasks():
    """Manage customer tasks."""
    pass

@tasks.command(name='list')
@click.argument('identifier', required=False)
def tasks_list(identifier):
    """List open tasks for customers."""
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
        c_name = cust['name']
        cust_dir = root / cust['slug']
        
        # Get open tasks from cache
        tasks_dir = cust_dir / 'tasks'
        tasks = load_tasks_from_json(tasks_dir)
        
        # Sort tasks by creation date
        def get_sort_key(t):
            return t.get('createdTime', t.get('startDate', ''))
            
        tasks.sort(key=get_sort_key, reverse=True)
        
        click.echo(f"\nCustomer: {c_name}")
        if not tasks:
            click.echo("  No open tasks.")
        else:
            for t in tasks:
                title = t.get('title', 'No Title')
                prio = t.get('priority', 0)
                prio_mark = "!" * prio if prio > 0 else ""
                click.echo(f"  - [ ] {title} {prio_mark}")
