"""
Trade Commands for Bullseye

Commands for trade management and utilities.
"""
import sys
import json
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

console = Console()


def get_db_url(config_path: Optional[str] = None) -> str:
    """Get database URL from config or default."""
    try:
        from ..configuration import Config
        config_obj = Config(config_path or "config.yaml")
        return config_obj.get('db_url', 'sqlite:///user_data/tradesv3.sqlite')
    except Exception:
        return 'sqlite:///user_data/tradesv3.sqlite'


@click.command(name='show-trades')
@click.option('--db-url', type=str, help='Database URL')
@click.option('--trade-ids', type=str, help='Specific trade IDs (comma-separated)')
@click.option('--pair', '-p', type=str, help='Filter by trading pair')
@click.option('--status', type=click.Choice(['open', 'closed', 'all']), default='all', help='Trade status')
@click.option('--limit', '-l', type=int, default=50, help='Maximum number of trades to show')
@click.option('--profit-only', is_flag=True, help='Show only profitable trades')
@click.option('--loss-only', is_flag=True, help='Show only losing trades')
@click.option('--print-json', is_flag=True, help='Output as JSON')
@click.option('--config', '-c', type=str, help='Configuration file')
def show_trades(db_url: Optional[str], trade_ids: Optional[str], pair: Optional[str],
                status: str, limit: int, profit_only: bool, loss_only: bool,
                print_json: bool, config: Optional[str]):
    """
    Show trade history
    
    Displays trades from the database with various filtering options.
    
    Examples:
        bullseye show-trades
        bullseye show-trades --status open
        bullseye show-trades --pair BTC/USDT --limit 10
        bullseye show-trades --profit-only
    """
    db_url = db_url or get_db_url(config)

    console.print("[bold green]Trade History[/bold green]")
    console.print(f"[dim]Database: {db_url}[/dim]\n")

    # This is a placeholder implementation
    # In a real implementation, this would query the database
    console.print("[yellow]Note: This command requires a database connection.[/yellow]")
    console.print("[dim]The database models need to be implemented to fetch actual trades.[/dim]\n")

    # Show example output
    if print_json:
        example_trades = [
            {
                'id': 1,
                'pair': 'BTC/USDT',
                'open_date': '2024-01-01 10:00:00',
                'close_date': '2024-01-01 12:00:00',
                'open_rate': 42000.0,
                'close_rate': 43000.0,
                'amount': 0.1,
                'profit': 100.0,
                'profit_percent': 2.38,
                'status': 'closed',
                'entry_tag': 'buy_signal',
                'exit_tag': 'sell_signal'
            }
        ]
        console.print(json.dumps(example_trades, indent=2))
    else:
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("ID", style="cyan")
        table.add_column("Pair", style="green")
        table.add_column("Open Date", style="blue")
        table.add_column("Close Date", style="blue")
        table.add_column("Profit %", style="yellow")
        table.add_column("Status", style="white")

        # Example row
        table.add_row("1", "BTC/USDT", "2024-01-01 10:00", "2024-01-01 12:00", "+2.38%", "closed")

        console.print(table)
        console.print("\n[dim](Example output - actual implementation requires database models)[/dim]")


@click.command(name='test-pairlist')
@click.option('--config', '-c', type=str, help='Configuration file')
@click.option('--exchange', '-e', type=str, help='Exchange name')
@click.option('--print-json', is_flag=True, help='Output as JSON')
def test_pairlist(config: Optional[str], exchange: Optional[str], print_json: bool):
    """
    Test pairlist configuration
    
    Shows which pairs would be selected based on the pairlist configuration.
    
    Examples:
        bullseye test-pairlist
        bullseye test-pairlist --config myconfig.yaml
        bullseye test-pairlist --print-json
    """
    try:
        from ..configuration import Config
        config_obj = Config(config or "config.yaml")
        exchange = exchange or config_obj.get('exchange.name', 'binance')
        pairlist_config = config_obj.get('pairlist', [])
    except Exception as e:
        console.print(f"[red]Error loading configuration: {e}[/red]")
        sys.exit(1)

    console.print("[bold green]Pairlist Configuration Test[/bold green]")
    console.print(f"[blue]Exchange:[/blue] {exchange}\n")

    # Parse pairlist configuration
    selected_pairs = []

    for item in pairlist_config:
        if isinstance(item, dict):
            method = item.get('method', '')
            method_config = item.get('config', {})

            if method == 'StaticPairList':
                pairs = method_config.get('pairs', [])
                selected_pairs.extend(pairs)
                console.print(f"[cyan]StaticPairList:[/cyan] {len(pairs)} pairs")
            elif method == 'VolumePairList':
                number_assets = method_config.get('number_assets', 20)
                console.print(f"[cyan]VolumePairList:[/cyan] Top {number_assets} by volume")
            elif method == 'PrecisionFilter':
                console.print("[cyan]PrecisionFilter:[/cyan] Applied")
            elif method == 'PriceFilter':
                console.print("[cyan]PriceFilter:[/cyan] Applied")
            elif method == 'SpreadFilter':
                console.print("[cyan]SpreadFilter:[/cyan] Applied")
        elif isinstance(item, str):
            selected_pairs.append(item)

    # Remove duplicates while preserving order
    seen = set()
    unique_pairs = []
    for pair in selected_pairs:
        if pair not in seen:
            seen.add(pair)
            unique_pairs.append(pair)

    console.print(f"\n[bold green]Selected Pairs ({len(unique_pairs)}):[/bold green]")

    if print_json:
        console.print(json.dumps(unique_pairs, indent=2))
    else:
        for i, pair in enumerate(unique_pairs, 1):
            console.print(f"  {i}. {pair}")

    console.print("\n[yellow]Note: Dynamic pairlists (VolumePairList) require exchange connection for full results.[/yellow]")


@click.command(name='convert-db')
@click.option('--source-db', type=str, required=True, help='Source database URL')
@click.option('--target-db', type=str, required=True, help='Target database URL')
@click.option('--dry-run', is_flag=True, help='Show what would be converted without converting')
def convert_db(source_db: str, target_db: str, dry_run: bool):
    """
    Convert database format
    
    Converts trades database between SQLite, PostgreSQL, and MySQL formats.
    
    Examples:
        bullseye convert-db --source-db sqlite:///trades.db --target-db postgresql://user:pass@localhost/trades
        bullseye convert-db --source-db sqlite:///trades.db --target-db mysql://user:pass@localhost/trades --dry-run
    """
    console.print("[bold green]Database Conversion[/bold green]")
    console.print(f"[blue]Source:[/blue] {source_db}")
    console.print(f"[blue]Target:[/blue] {target_db}")

    if dry_run:
        console.print("\n[yellow]Dry run mode - no data will be converted[/yellow]")

    # Determine database types
    source_type = 'unknown'
    target_type = 'unknown'

    if source_db.startswith('sqlite'):
        source_type = 'SQLite'
    elif source_db.startswith('postgresql'):
        source_type = 'PostgreSQL'
    elif source_db.startswith('mysql'):
        source_type = 'MySQL'

    if target_db.startswith('sqlite'):
        target_type = 'SQLite'
    elif target_db.startswith('postgresql'):
        target_type = 'PostgreSQL'
    elif target_db.startswith('mysql'):
        target_type = 'MySQL'

    console.print(f"\n[blue]Conversion:[/blue] {source_type} -> {target_type}")

    if dry_run:
        console.print("\n[dim]The following tables would be converted:[/dim]")
        console.print("  - trades")
        console.print("  - orders")
        console.print("  - pairlocks")
        console.print("  - key_value_store")
        return

    # Implementation would:
    # 1. Connect to source database
    # 2. Read all data
    # 3. Connect to target database
    # 4. Create tables
    # 5. Insert data

    console.print("\n[yellow]Database conversion - implementation pending[/yellow]")
    console.print("[dim]This command will convert all tables from source to target database[/dim]")
