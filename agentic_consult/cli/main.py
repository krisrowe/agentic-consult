import click

from .config import config
from .customers import customers
from .backup import backup
from .precommit import precommit
from .issues import issues
from .tasks import tasks
from .refresh import refresh
from .analyze import analyze
from .user_home import user_home_cli

@click.group()
def main():
    """Consult CLI: Agentic Consultant Tools"""
    pass

main.add_command(config)
main.add_command(customers)
main.add_command(backup)
main.add_command(precommit)
main.add_command(issues)
main.add_command(tasks)
main.add_command(refresh)
main.add_command(analyze)
main.add_command(user_home_cli)

if __name__ == "__main__":
    main()
