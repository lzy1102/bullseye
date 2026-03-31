"""
Bullseye - CLI Entry Point

Command-line interface for the Bullseye quantitative trading framework.
"""
import sys
import logging
from datetime import datetime
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from . import __version__
from .commands import (
    # Config commands
    create_userdir, new_config, show_config,
    # Data commands
    download_data, list_data, convert_data, convert_trade_data, trades_to_ohlcv,
    # List commands
    list_markets, list_pairs, list_hyperoptloss, list_timeframes, list_exchanges,
    # Backtest commands
    backtesting_show, backtesting_analysis,
    # Trade commands
    show_trades, test_pairlist, convert_db,
    # Plot commands
    plot_dataframe, plot_profit,
    # Hyperopt commands
    hyperopt_list, hyperopt_show, strategy_updater,
    # Webserver commands
    webserver,
)
from .optimize.analysis.lookahead import lookahead_analysis
from .optimize.analysis.recursive import recursive_analysis

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
@click.option('--config', '-c', type=str, help='Configuration file path')
@click.pass_context
def trade(ctx, dry: bool, live: bool, strategy: Optional[str], config: Optional[str]):
    """
    Start trading bot

    Examples:
        bullseye trade --dry
        bullseye trade --dry --strategy SampleStrategy --config config.yaml
        bullseye trade --live --strategy MyStrategy
    """
    if dry and live:
        console.print("[red]Cannot specify both --dry and --live[/red]")
        sys.exit(1)

    # Get config path from option or context
    config_path = config or ctx.obj.get('config')

    # Load configuration
    from .configuration import Config
    try:
        config_obj = Config(config_path)
    except FileNotFoundError:
        console.print(f"[red]Configuration file not found: {config_path}[/red]")
        console.print("[yellow]Using default configuration[/yellow]")
        config_obj = Config()

    # Set run mode
    if dry:
        config_obj.dry_run = True
    elif live:
        config_obj.dry_run = False

    # Override strategy if provided
    if strategy:
        config_obj.set('strategy', strategy)

    mode = "dry_run" if config_obj.dry_run else "live"

    console.print(f"[green]Starting Bullseye in {mode} mode...[/green]")
    console.print(f"[blue]Strategy: {config_obj.strategy or 'not specified'}[/blue]")
    console.print(f"[blue]Exchange: {config_obj.exchange_name}[/blue]")
    console.print(f"[blue]Pairs: {config_obj.pairlist}[/blue]" if config_obj.pairlist else "")
    console.print("[yellow]Press Ctrl+C to stop[/yellow]\n")

    # Load and run bot
    from .bot import BullseyeBot
    from .strategy.interface import IStrategy
    import importlib
    from pathlib import Path

    strategy_class = None

    # Try to load strategy if specified
    if config_obj.strategy:
        try:
            # Try loading from user_data/strategies
            strategy_path = Path(config_obj.strategy_path)
            if strategy_path.exists():
                import sys
                sys.path.insert(0, str(strategy_path))

            # Try direct import
            try:
                module = importlib.import_module(config_obj.strategy)
                strategy_class = getattr(module, config_obj.strategy)
            except (ImportError, AttributeError):
                # Try from strategies folder
                try:
                    module = importlib.import_module(f"strategies.{config_obj.strategy}")
                    strategy_class = getattr(module, config_obj.strategy)
                except (ImportError, AttributeError):
                    pass

        except Exception as e:
            console.print(f"[red]Error loading strategy: {e}[/red]")
            console.print("[yellow]Will try to load from configuration[/yellow]")

    try:
        bot = BullseyeBot(config_obj, strategy_class)
        bot.run()
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping Bullseye...[/yellow]")
    except Exception as e:
        console.print(f"\n[red]Error running bot: {e}[/red]")
        logger.exception("Bot error")
        sys.exit(1)


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


# Import download_data from commands
from .commands.data_commands import download_data as download_data_cmd


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
@click.option('--timeframe', '-tf', type=str, default='5m', help='Default timeframe')
@click.option('--output', '-o', type=str, help='Output directory')
@click.pass_context
def new_strategy(ctx, strategy: Optional[str], template: str, timeframe: str, output: Optional[str]):
    """
    Create a new strategy template

    Examples:
        bullseye new-strategy --strategy MyStrategy
        bullseye new-strategy --strategy MyStrategy --template minimal
        bullseye new-strategy --strategy MyStrategy --template advanced --timeframe 1h
    """
    strategy = strategy or "MyStrategy"

    console.print(f"[green]Creating new strategy: {strategy}[/green]")
    console.print(f"[blue]Template: {template}[/blue]")
    console.print(f"[blue]Timeframe: {timeframe}[/blue]")

    try:
        from .strategy import create_strategy_template, list_available_templates

        # Check if template exists
        templates = list_available_templates()
        if template not in templates:
            console.print(f"[red]Unknown template: {template}[/red]")
            console.print(f"[yellow]Available templates: {list(templates.keys())}[/yellow]")
            sys.exit(1)

        # Create strategy file
        file_path = create_strategy_template(
            strategy_name=strategy,
            template=template,
            output_dir=output,
            timeframe=timeframe,
        )

        console.print(f"\n[green]✓ Strategy file created: {file_path}[/green]")
        console.print(f"\n[yellow]Next steps:[/yellow]")
        console.print(f"  1. Edit the strategy file: {file_path}")
        console.print(f"  2. Implement your trading logic")
        console.print(f"  3. Run backtest: bullseye backtesting --strategy {strategy}")

    except FileExistsError as e:
        console.print(f"[red]Error: {e}[/red]")
        console.print("[yellow]Use a different strategy name or delete the existing file[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error creating strategy: {e}[/red]")
        logger.exception("Strategy creation error")
        sys.exit(1)


@cli.command()
@click.option('--templates', is_flag=True, help='List available templates instead of strategies')
@click.pass_context
def list_strategies(ctx, templates: bool):
    """List all available strategies or templates"""
    if templates:
        # List templates
        console.print("[green]Available strategy templates:[/green]\n")

        from .strategy import list_available_templates

        template_list = list_available_templates()

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Template", style="cyan")
        table.add_column("Description")

        for name, desc in template_list.items():
            table.add_row(name, desc)

        console.print(table)
        console.print("\n[yellow]Usage: bullseye new-strategy --strategy MyStrategy --template <template>[/yellow]")
    else:
        # List strategies
        console.print("[green]Available strategies:[/green]\n")

        from pathlib import Path

        # Find strategies directory
        strategy_dirs = [
            Path("user_data/strategies"),
            Path("strategies"),
        ]

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Strategy", style="cyan")
        table.add_column("File", style="green")
        table.add_column("Modified")

        found_any = False
        for strategy_dir in strategy_dirs:
            if strategy_dir.exists():
                for file in strategy_dir.glob("*.py"):
                    if file.name.startswith("_"):
                        continue

                    strategy_name = file.stem
                    modified = datetime.fromtimestamp(file.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                    table.add_row(strategy_name, str(file), modified)
                    found_any = True

        if found_any:
            console.print(table)
        else:
            console.print("[yellow]No strategies found.[/yellow]")
            console.print("[yellow]Create one with: bullseye new-strategy --strategy MyStrategy[/yellow]")


@cli.command()
@click.pass_context
def init_project(ctx):
    """
    Initialize project structure

    Creates necessary directories and example files.
    """
    console.print("[green]Initializing Bullseye project...[/green]\n")

    from pathlib import Path

    # Create directory structure
    directories = [
        "user_data",
        "user_data/strategies",
        "user_data/data",
        "user_data/logs",
        "user_data/notebooks",
        "user_data/hyperopt",
    ]

    for dir_path in directories:
        path = Path(dir_path)
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            console.print(f"[green]✓ Created: {dir_path}[/green]")
        else:
            console.print(f"[blue]  Exists: {dir_path}[/blue]")

    # Create default config if not exists
    config_path = Path("config.yaml")
    if not config_path.exists():
        import shutil
        example_config = Path("config.yaml.example")
        if example_config.exists():
            shutil.copy(example_config, config_path)
            console.print(f"[green]✓ Created: config.yaml (from example)[/green]")
        else:
            console.print("[yellow]  config.yaml.example not found, skipping[/yellow]")
    else:
        console.print(f"[blue]  Exists: config.yaml[/blue]")

    # Create sample strategy
    try:
        from .strategy import create_strategy_template

        strategy_path = Path("user_data/strategies/SampleStrategy.py")
        if not strategy_path.exists():
            create_strategy_template(
                strategy_name="SampleStrategy",
                template="full",
                output_dir="user_data/strategies",
            )
            console.print(f"[green]✓ Created: user_data/strategies/SampleStrategy.py[/green]")
        else:
            console.print(f"[blue]  Exists: user_data/strategies/SampleStrategy.py[/blue]")
    except Exception as e:
        console.print(f"[yellow]  Could not create sample strategy: {e}[/yellow]")

    console.print("\n[green]✓ Project initialized successfully![/green]")
    console.print("\n[yellow]Next steps:[/yellow]")
    console.print("  1. Edit config.yaml with your settings")
    console.print("  2. Create strategies in user_data/strategies/")
    console.print("  3. Run: bullseye trade --dry --strategy SampleStrategy")


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


# Register new commands
cli.add_command(create_userdir)
cli.add_command(new_config)
cli.add_command(show_config)
cli.add_command(download_data_cmd)
cli.add_command(list_data)
cli.add_command(convert_data)
cli.add_command(convert_trade_data)
cli.add_command(trades_to_ohlcv)
cli.add_command(list_markets)
cli.add_command(list_pairs)
cli.add_command(list_hyperoptloss)
cli.add_command(backtesting_show)
cli.add_command(backtesting_analysis)
cli.add_command(show_trades)
cli.add_command(test_pairlist)
cli.add_command(convert_db)

# Register webserver commands
cli.add_command(webserver)

# Register analysis commands
cli.add_command(lookahead_analysis)
cli.add_command(recursive_analysis)

if __name__ == "__main__":
    cli()
