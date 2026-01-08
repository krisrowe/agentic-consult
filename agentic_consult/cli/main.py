import click

from .config import config
from .customers import customers
from .backup import backup
from .precommit import precommit
from .issues import issues
from .models import models
from .tasks import tasks
from .gemini import gemini
from .user_home import user_home_cli
from .workspace import workspace
from .restore import restore
from .context import context
from .chat import chat

@click.group()
def main():
    """Consult CLI: Agentic Consultant Tools"""
    pass

main.add_command(config)
main.add_command(customers)
main.add_command(backup)
main.add_command(restore)
main.add_command(precommit)
main.add_command(issues)
main.add_command(models)
main.add_command(tasks)
main.add_command(gemini)
main.add_command(user_home_cli)
main.add_command(workspace)
main.add_command(context)
main.add_command(chat)

if __name__ == "__main__":
    main()
