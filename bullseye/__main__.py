"""
Bullseye - CLI Entry Point

Command-line interface for the Bullseye quantitative trading framework.
"""
import sys
import logging
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from . import __version__

console = Console()
logger = logging.getLogger(__name__)


# ==================== Main CLI Group ====================

@click.group()
@click.version_option(version=__version__)
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
@click.option('--config', '-c', type=str, help='Configuration file path')
@click.pass_context
def cli(ctx, verbose: bool, config: Optional[str]):
    """
    Bullseye - Quantitative Trading Framework

    Freqtrade-compatible quantitative trading framework supporting
    crypto, stock, and futures markets.
    """
    # Set up logging
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Store context
    ctx.ensure_object(dict)
    ctx.obj['verbose'] = verbose
    ctx.obj['config'] = config


# ==================== Trading Commands ====================

@cli.command()
@click.option('--dry', is_flag=True, help='Run in dry-run (paper trading) mode')
@click.option('--live', is_flag=True, help='Run in live trading mode')
@click.option('--strategy', '-s', type=str, help='Strategy name')
@click.pass_context
def trade(ctx, dry: bool, live: bool, strategy: Optional[str]):
    """
    Start trading bot

    Examples:
        bullseye trade --dry
        bullseye trade --live --strategy MyStrategy
    """
    if dry and live:
        console.print("[red]Cannot specify both --dry and --live[/red]")
        sys.exit(1)

    mode = "dry_run" if dry else "live" if live else "config"

    console.print(f"[green]Starting trading in {mode} mode...[/green]")
    console.print(f"[blue]Strategy: {strategy or 'from config'}[/blue]")
    console.print("[yellow]Press Ctrl+C to stop[/yellow]\n")

    # TODO: Implement trading logic
    # from .bot import BullseyeBot
    # bot = BullseyeBot(config=ctx.obj['config'], strategy=strategy)
    # bot.run()

    # Keep the bot running (temporary until full implementation)
    import time
    try:
        while True:
            console.print(f"[green]●[/green] Bullseye running in {mode} mode | {time.strftime('%Y-%m-%d %H:%M:%S')}", end='\r')
            time.sleep(5)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping Bullseye...[/yellow]")
        sys.exit(0)


@cli.command()
@click.option('--strategy', '-s', type=str, required=True, help='Strategy name')
@click.option('--timeframe', '-tf', type=str, default='5m', help='Timeframe')
@click.option('--timerange', type=str, help='Time range (e.g., 20240101-20241231)')
@click.option('--config', '-c', type=str, help='Configuration file')
@click.pass_context
def backtesting(ctx, strategy: str, timeframe: str, timerange: Optional[str], config: Optional[str]):
    """
    Run backtesting

    Examples:
        bullseye backtesting --strategy MyStrategy
        bullseye backtesting --strategy MyStrategy --timerange 20240101-20241231
    """
    console.print(f"[green]Running backtest...[/green]")
    console.print(f"[blue]Strategy: {strategy}[/blue]")
    console.print(f"[blue]Timeframe: {timeframe}[/blue]")
    if timerange:
        console.print(f"[blue]Time range: {timerange}[/blue]")

    # TODO: Implement backtesting logic
    # from .backtesting import BacktestEngine
    # engine = BacktestEngine(config=config or ctx.obj['config'])
    # engine.run(strategy=strategy, timeframe=timeframe, timerange=timerange)


@cli.command()
@click.option('--exchange', type=str, help='Exchange name')
@click.option('--pairs', type=str, help='Trading pairs (comma-separated)')
@click.option('--timeframes', type=str, help='Timeframes (comma-separated)')
@click.option('--days', type=int, default=30, help='Number of days to download')
@click.option('--timerange', type=str, help='Time range (e.g., 20240101-20241231)')
@click.pass_context
def download_data(ctx, exchange: Optional[str], pairs: Optional[str],
                  timeframes: Optional[str], days: int, timerange: Optional[str]):
    """
    Download market data

    Examples:
        bullseye download-data --exchange binance --pairs BTC/USDT,ETH/USDT
        bullseye download-data --exchange binance --days 30
        bullseye download-data --timerange 20240101-20241231
    """
    console.print(f"[green]Downloading data...[/green]")

    # TODO: Implement data download logic
    # from .data import DataDownloader
    # downloader = DataDownloader(exchange=exchange)
    # downloader.download(pairs=pairs, timeframes=timeframes, days=days, timerange=timerange)


@cli.command()
@click.option('--hyperopt', type=str, help='Hyperopt class name')
@click.option('--epochs', type=int, default=100, help='Number of optimization epochs')
@click.option('--spaces', type=str, default='all', help='Optimization spaces')
@click.option('--jobs', type=int, default=-1, help='Number of parallel jobs')
@click.pass_context
def hyperopt(ctx, hyperopt: Optional[str], epochs: int, spaces: str, jobs: int):
    """
    Run hyperparameter optimization

    Examples:
        bullseye hyperopt --hyperopt MyHyperOpt --epochs 100
        bullseye hyperopt --spaces buy,sell
    """
    console.print(f"[green]Running hyperopt...[/green]")
    console.print(f"[blue]Epochs: {epochs}[/blue]")
    console.print(f"[blue]Spaces: {spaces}[/blue]")

    # TODO: Implement hyperopt logic
    # from .optimize import HyperoptEngine
    # engine = HyperoptEngine(config=ctx.obj['config'])
    # engine.run(hyperopt=hyperopt, epochs=epochs, spaces=spaces, jobs=jobs)


# ==================== Strategy Commands ====================

@cli.command()
@click.option('--strategy', type=str, help='Strategy name')
@click.option('--template', type=str, default='full', help='Template level (minimal/full/advanced)')
@click.pass_context
def new_strategy(ctx, strategy: Optional[str], template: str):
    """
    Create a new strategy template

    Examples:
        bullseye new-strategy --strategy MyStrategy
        bullseye new-strategy --strategy MyStrategy --template minimal
    """
    strategy = strategy or "MyStrategy"
    console.print(f"[green]Creating new strategy: {strategy}[/green]")
    console.print(f"[blue]Template: {template}[/blue]")

    # TODO: Implement strategy creation
    # from .strategy import create_strategy_template
    # create_strategy_template(strategy, template)


@cli.command()
@click.pass_context
def list_strategies(ctx):
    """List all available strategies"""
    console.print("[green]Available strategies:[/green]")

    # TODO: List strategies from user_data/strategies
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Strategy", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Timeframe")

    # Example strategies
    table.add_row("SampleStrategy", "✓ Ready", "5m")
    table.add_row("MyStrategy", "✓ Ready", "1h")

    console.print(table)


# ==================== Utility Commands ====================

@cli.command()
def list_timeframes():
    """List supported timeframes"""
    console.print("[green]Supported timeframes:[/green]")

    timeframes = [
        ("1m", "1 minute"),
        ("5m", "5 minutes"),
        ("15m", "15 minutes"),
        ("30m", "30 minutes"),
        ("1h", "1 hour"),
        ("4h", "4 hours"),
        ("1d", "1 day"),
        ("1w", "1 week"),
    ]

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Code", style="cyan")
    table.add_column("Description")

    for code, desc in timeframes:
        table.add_row(code, desc)

    console.print(table)


@cli.command()
def list_exchanges():
    """List supported exchanges"""
    console.print("[green]Supported exchanges:[/green]")

    # Crypto exchanges (CCXT)
    console.print("\n[bold cyan]Cryptocurrency (CCXT):[/bold cyan]")
    crypto_exchanges = [
        "binance", "okx", "bybit", "gate.io", "kucoin",
        "bitfinex", "kraken", "coinbase", "huobi", "bitget"
    ]
    for exchange in crypto_exchanges:
        console.print(f"  • {exchange}")

    # Stock exchanges
    console.print("\n[bold cyan]Stock (China):[/bold cyan]")
    stock_exchanges = ["XTP (中泰证券)", "TORA (华鑫奇点)", "OST (东证)", "EMT (东方财富)"]
    for exchange in stock_exchanges:
        console.print(f"  • {exchange}")

    # Futures exchanges
    console.print("\n[bold cyan]Futures (China):[/bold cyan]")
    future_exchanges = ["CTP (SimNow)", "MiniCTP", "FEMAS (飞马)", "UFT (恒生UFT)"]
    for exchange in future_exchanges:
        console.print(f"  • {exchange}")

    # International
    console.print("\n[bold cyan]International:[/bold cyan]")
    intl_exchanges = ["IB (盈透证券)", "TAP (易盛)", "DA (直达)"]
    for exchange in intl_exchanges:
        console.print(f"  • {exchange}")


# ==================== Info Commands ====================

@cli.command()
def version():
    """Show version information"""
    console.print(f"[bold green]Bullseye[/bold green] version {__version__}")
    console.print("Freqtrade-compatible quantitative trading framework")
    console.print("\n[blue]Features:[/blue]")
    console.print("  • 100% Freqtrade strategy compatible")
    console.print("  • Multi-market support (crypto, stock, futures)")
    console.print("  • Event-driven architecture")
    console.print("  • Unified data format")


@cli.command()
def info():
    """Show system information"""
    console.print("[bold green]Bullseye System Information[/bold green]\n")

    table = Table(show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Python Version", sys.version.split()[0])
    table.add_row("Platform", sys.platform)

    # Check dependencies
    try:
        import ccxt
        table.add_row("CCXT", ccxt.__version__)
    except ImportError:
        table.add_row("CCXT", "[red]Not installed[/red]")

    try:
        import pandas
        table.add_row("Pandas", pandas.__version__)
    except ImportError:
        table.add_row("Pandas", "[red]Not installed[/red]")

    try:
        import sqlalchemy
        table.add_row("SQLAlchemy", sqlalchemy.__version__)
    except ImportError:
        table.add_row("SQLAlchemy", "[red]Not installed[/red]")

    console.print(table)


if __name__ == "__main__":
    cli()
