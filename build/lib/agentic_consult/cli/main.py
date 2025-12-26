import click

from .config import config
from .customers import customers
from .backup import backup
from .precommit import precommit
from .issues import issues
from .tasks import tasks
from .refresh import refresh

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

if __name__ == "__main__":
    main()
