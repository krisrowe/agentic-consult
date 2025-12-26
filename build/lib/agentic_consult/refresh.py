import os
import datetime
from pathlib import Path
import click

def build_prompt(tpl, config, customer, emails=None, tasks=None, customer_dir=None):
    """
    Substitutes placeholders in the prompt template.
    """
    customer_name = customer.get("name")
    customer_slug = customer.get("slug")
    
    today_str = datetime.date.today().isoformat()
    reminder_minutes = os.environ.get("REMINDER_MINUTES", str(config.get("reminder_minutes", 5)))
    ticktick_project = config.get("ticktick_project", "Work")
    
    from agentic_consult.customers import get_active_customers_root
    
    if not customer_dir:
        customers_root = get_active_customers_root()
        customer_dir = customers_root / customer_slug

    customer_issues = customer_dir / "issues"
    customer_emails = customer_dir / "emails"
    customer_tasks = customer_dir / "tasks"
    
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

    # Read content for embedding
    import json
    
    emails_content = []
    if emails is not None:
        emails_content = emails
    elif customer_emails.exists():
        for f in customer_emails.glob("*.json"):
            try:
                with open(f, 'r') as fh:
                    data = json.load(fh)
                    if isinstance(data, list):
                        emails_content.extend(data)
                    else:
                        emails_content.append(data)
            except Exception:
                pass
                
    tasks_content = []
    if tasks is not None:
        tasks_content = tasks
    elif customer_tasks.exists():
        for f in customer_tasks.glob("*.json"):
            try:
                with open(f, 'r') as fh:
                    data = json.load(fh)
                    if isinstance(data, list):
                        tasks_content.extend(data)
                    else:
                        tasks_content.append(data)
            except Exception:
                pass

    # Read issues content
    issues_content = []
    issues_path = Path(issues_dir)
    if issues_path.exists():
        for f in issues_path.glob("*.md"):
            try:
                issues_content.append({
                    "file": f.name,
                    "content": f.read_text()[:2000] # Truncate to avoid context limit issues
                })
            except Exception:
                pass

    prompt = tpl.replace("<PROJECT>", ticktick_project)
    prompt = prompt.replace("<CUSTOMER>", customer_name)
    prompt = prompt.replace("<CUSTOMER_SEARCH>", customer_name)
    prompt = prompt.replace("<CUSTOMER_PREFIX>", customer_name)
    prompt = prompt.replace("<TODAY>", today_str)
    prompt = prompt.replace("<REMINDER_MINUTES>", str(reminder_minutes))
    
    # Inject issues content or fallback to directory path if empty/too large (but prefer content)
    if issues_content:
        prompt = prompt.replace("<ISSUES_DIR>", json.dumps(issues_content, indent=2))
    else:
        prompt = prompt.replace("<ISSUES_DIR>", str(Path(issues_dir).resolve()))
        
    prompt = prompt.replace("<EMAILS>", json.dumps(emails_content, indent=2))
    prompt = prompt.replace("<TASKS>", json.dumps(tasks_content, indent=2))
    
    return prompt
