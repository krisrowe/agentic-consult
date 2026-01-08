import click
from agentic_consult.config import get_model_help_text
from agentic_consult.sdk.context import analyze_context, revise_context

@click.group()
def context():
    """Manage Gemini context files (GEMINI.md)."""
    pass

@context.command()
@click.argument("prompt")
@click.option(
    "--scope", 
    type=click.Choice(["project", "user"]),
    default="project",
    help="Scope of the context file to analyze."
)
@click.option("--model", "-m", help=f"Override the Gemini model. {get_model_help_text()}")
def analyze(prompt, scope, model):
    """
    Analyze the GEMINI.md context file using an LLM.

    Reads the existing GEMINI.md (based on scope) and answers your question
    about its content. Does NOT modify the file.
    """
    try:
        result = analyze_context(scope, prompt, model)
        click.echo(result)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        click.get_current_context().exit(1)
    except Exception as e:
        click.echo(f"Error calling Gemini: {e}", err=True)
        click.get_current_context().exit(1)


@context.command()
@click.argument("prompt")
@click.option(
    "--scope", 
    type=click.Choice(["project", "user"]), 
    default="project",
    help="Scope of the context file to revise."
)
@click.option("--model", "-m", help=f"Override the Gemini model. {get_model_help_text()}")
def revise(prompt, scope, model):
    """
    Revise the GEMINI.md context file using an LLM.

    Reads the existing GEMINI.md (based on scope), sends it to Gemini
    with your revision prompt, and overwrites the file with the result.
    A backup (.bak) is created before overwriting.
    """
    try:
        click.echo(f"Consulting Gemini to revise context...", err=True)
        result = revise_context(scope, prompt, model)
        click.echo(result, err=True)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        click.get_current_context().exit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        click.get_current_context().exit(1)
