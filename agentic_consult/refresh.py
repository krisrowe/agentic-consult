import os
import datetime
from pathlib import Path
import click

def build_prompt(tpl, config, customer):
    """
    Substitutes placeholders in the prompt template.
    """
    customer_name = customer.get("name")
    customer_slug = customer.get("slug")
    
    today_str = datetime.date.today().isoformat()
    reminder_minutes = os.environ.get("REMINDER_MINUTES", str(config.get("reminder_minutes", 5)))
    ticktick_project = config.get("ticktick_project", "Work")
    
    # Resolve issues dir (simplified for SDK logic)
    # Ideally the SDK should have a standard way to resolve paths too
    app_config_dir = Path(click.get_app_dir('agentic-consult'))
    customers_root = app_config_dir / 'customers'
    if not customers_root.exists():
        customers_root = Path("./customers")
        
    customer_issues = customers_root / customer_slug / "issues"
    customer_emails = customers_root / customer_slug / "emails"
    customer_tasks = customers_root / customer_slug / "tasks"
    
    default_issues = Path(click.get_app_dir('agentic-consult')).parent.parent / 'share' / 'agentic-consult' / 'issues'
    
    cfg_issues = config.get("issues_dir")
    if cfg_issues == "./issues":
        cfg_issues = None
        
    issues_dir = os.environ.get("ISSUES_DIR")
    if not issues_dir:
        if customer_issues.exists():
            issues_dir = str(customer_issues)
        else:
            issues_dir = cfg_issues or str(default_issues)

    prompt = tpl.replace("<TICKTICK_PROJECT>", ticktick_project)
    prompt = prompt.replace("<CUSTOMER>", customer_name)
    prompt = prompt.replace("<CUSTOMER_SEARCH>", customer_name)
    prompt = prompt.replace("<CUSTOMER_PREFIX>", customer_name)
    prompt = prompt.replace("<TODAY>", today_str)
    prompt = prompt.replace("<REMINDER_MINUTES>", str(reminder_minutes))
    prompt = prompt.replace("<ISSUES_DIR>", str(Path(issues_dir).resolve()))
    prompt = prompt.replace("<EMAILS_DIR>", str(customer_emails.resolve()))
    prompt = prompt.replace("<TASKS_DIR>", str(customer_tasks.resolve()))
    
    return prompt
