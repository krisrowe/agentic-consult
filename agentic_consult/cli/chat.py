import click
import logging
import sys
import json
from agentic_consult.chat.triage import get_chat_mentions

logger = logging.getLogger(__name__)

@click.group()
def chat():
    """Google Chat tools."""
    pass

@chat.group()
def mentions():
    """Manage/view chat mentions."""
    pass

@mentions.command(name='list')
@click.option('--scan-spaces-limit', default=None, type=int, help='Maximum number of active spaces to scan (default: 20).')
@click.option('--unanswered-only/--all', default=True, help='Show only unanswered mentions.')
@click.option('--format', default='text', type=click.Choice(['text', 'json'], case_sensitive=False), help='Output format.')
@click.option('--days-back', multiple=True, help='Scan rules in format "NU:ND" (e.g. "25u:1d"). NU=Max Users, ND=Days Back.')
@click.option('--scan-messages-limit', default=None, type=int, help='Global limit on total messages scanned across all spaces.')
@click.option('--verbose', is_flag=True, help='Include detailed scanning metadata and source stats.')
def list_mentions(scan_spaces_limit, unanswered_only, format, days_back, scan_messages_limit, verbose):
    """List recent mentions and unread DMs."""
    import os
    if os.environ.get('LOG_LEVEL', '').upper() == 'DEBUG':
        logging.basicConfig(level=logging.DEBUG)
        logging.getLogger('gwsa.sdk.chat.triage').setLevel(logging.DEBUG)

    # Parse days_back rules
    tiers = None
    if days_back:
        tiers = []
        for rule in days_back:
            try:
                # Expected format: "25u:1d"
                parts = rule.lower().split(':')
                if len(parts) != 2:
                    raise ValueError("Invalid format")
                
                max_users_str = parts[0].replace('u', '')
                days_str = parts[1].replace('d', '')
                
                max_members = int(max_users_str)
                lookback_days = int(days_str)
                
                tiers.append({'max_members': max_members, 'lookback_days': lookback_days})
            except Exception:
                click.echo(f"Error: Invalid --days-back format '{rule}'. Expected 'NU:ND' (e.g. '25u:1d').", err=True)
                sys.exit(1)

    try:
        if format == 'text':
            spaces_str = scan_spaces_limit if scan_spaces_limit is not None else "default"
            msgs_str = scan_messages_limit if scan_messages_limit is not None else "default"
            click.echo(f"Scanning for mentions (spaces={spaces_str}, msgs={msgs_str})...")
        
        results = get_chat_mentions(
            limit=scan_spaces_limit, 
            unanswered_only=unanswered_only,
            tiers=tiers,
            message_limit=scan_messages_limit,
            verbose=verbose
        )
        
        if format == 'json':
            click.echo(json.dumps(results, indent=2))
            return

        mentions = results.get("mentions", [])
        stats = results
        
        if not mentions:
            click.echo("No mentions found.")
        else:
            from rich.console import Console
            from rich.table import Table
            console = Console()
            
            table = Table(show_header=True, header_style="bold green")
            table.add_column("Space", style="cyan")
            table.add_column("Sender", style="yellow")
            table.add_column("Time", style="dim")
            table.add_column("Message")
            
            click.echo(f"\nFound {len(mentions)} mentions (scanned {stats.get('scanned_count', '?')} spaces):")
            
            for m in mentions:
                sender = m.get('sender', 'Unknown')
                text = m.get('text', '')
                space_name = m.get('space', 'Unknown Space')
                msg_time = m.get('time', 'Unknown Time')
                
                # Truncate text for table
                if len(text) > 100:
                    text = text[:97] + "..."
                    
                table.add_row(space_name, sender, msg_time, text)
            
            console.print(table)
        
        # Verbose metadata reporting
        if verbose:
            from rich.console import Console
            from rich.table import Table
            
            console = Console()
            
            # Source Stats Table
            if 'source' in results:
                src = results['source']
                click.echo("\nScanning Metadata:")
                table = Table(show_header=True, header_style="bold magenta")
                table.add_column("Space Name", style="dim")
                table.add_column("Type")
                table.add_column("Users", justify="right")
                table.add_column("Lookback", justify="right")
                table.add_column("Scan", justify="right")
                table.add_column("Range", justify="right")
                table.add_column("Hits", justify="right")
                
                for s in src.get('spaces', []):
                    table.add_row(
                        s.get('name', 'Unknown'),
                        s.get('type', ''),
                        str(s.get('members', '')),
                        f"{s.get('lookback_days', '')}d",
                        str(s.get('messages_scanned', '')),
                        str(s.get('messages_in_range', '')),
                        str(s.get('mentions_found', ''))
                    )
                
                console.print(table)
                click.echo(f"Total Messages Scanned: {src.get('total_messages_scanned')}")
                click.echo(f"Exit Reason: {src.get('exit_reason')}")

            # API Stats Table
            api_stats = stats.get('api_stats', {})
            if api_stats:
                click.echo("\nAPI Stats (logical calls):")
                api_table = Table(show_header=True, header_style="bold cyan")
                api_table.add_column("API Method")
                api_table.add_column("Count", justify="right")
                
                total = 0
                for call_type, count in sorted(api_stats.items()):
                    api_table.add_row(call_type, str(count))
                    total += count
                
                api_table.add_row("TOTAL", str(total), style="bold")
                console.print(api_table)
                
    except Exception as e:
        logger.error(f"Error listing mentions: {e}")
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)