"""
Bullseye - CLI Entry Point

Command-line interface for the Bullseye quantitative trading framework.
Compatible with Freqtrade command style.
"""
import sys
import logging
from datetime import datetime
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

try:
    from . import __version__
except ImportError:
    __version__ = "0.1.0"
from .commands import (
    # Config commands
    create_userdir, new_config, show_config,
    # Data commands
    download_data, list_data, convert_data, convert_trade_data, trades_to_ohlcv,
    # List commands
    list_markets, list_pairs, list_hyperoptloss,
    # Backtest commands
    backtesting_show, backtesting_analysis,
    # Trade commands
    show_trades, test_pairlist, convert_db,
    # Plot commands
    plot_dataframe, plot_profit,
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


# ==================== Backtesting Command ====================

@cli.command()
@click.option('--strategy', '-s', type=str, required=True, help='Strategy name')
@click.option('--timeframe', '-tf', type=str, help='Timeframe (e.g. 5m, 1h, 30m)')
@click.option('--timerange', type=str, help='Time range (e.g., 20240101-20241231)')
@click.option('--config', '-c', type=str, help='Configuration file')
@click.option('--stake-amount', type=float, help='Stake amount per trade')
@click.option('--initial-balance', type=float, default=1000, help='Initial balance')
@click.option('--max-open-trades', type=int, help='Max concurrent open trades')
@click.option('--fee', type=float, default=0.001, help='Fee rate (e.g., 0.001 for 0.1%%)')
@click.option('--export', type=str, help='Export results to JSON file')
@click.pass_context
def backtesting(ctx, strategy: str, timeframe: str, timerange: Optional[str],
                config: Optional[str], stake_amount: Optional[float],
                initial_balance: float, max_open_trades: Optional[int],
                fee: float, export: Optional[str]):
    """
    Run backtesting

    Examples:
        bullseye backtesting --strategy MyStrategy
        bullseye backtesting --strategy MyStrategy --timerange 20240101-20241231
        bullseye backtesting --strategy MyStrategy --initial-balance 10000 --fee 0.001
    """
    console.print(f"[bold green]Running backtest...[/bold green]")
    console.print(f"[blue]Strategy:[/blue] {strategy}")
    if timeframe:
        console.print(f"[blue]Timeframe:[/blue] {timeframe}")
    if timerange:
        console.print(f"[blue]Time range:[/blue] {timerange}")
    console.print(f"[blue]Initial balance:[/blue] {initial_balance}")
    console.print(f"[blue]Fee rate:[/blue] {fee * 100:.2f}%")

    config_path = config or ctx.obj.get('config')
    try:
        from .configuration import Config
        config_obj = Config(config_path)
    except FileNotFoundError:
        config_obj = Config()

    from .backtesting import BacktestEngine

    engine = BacktestEngine(config=config_obj)

    try:
        result = engine.run(
            strategy_name=strategy,
            timeframe=timeframe,
            timerange=timerange,
            stake_amount=stake_amount,
            max_open_trades=max_open_trades,
            initial_balance=initial_balance,
            fee=fee,
            export=export,
        )

        m = result.metrics
        console.print()
        console.print(Panel(
            f"[bold cyan]Strategy: {result.strategy_name}[/bold cyan]",
            expand=False,
        ))

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Total Trades", str(m.total_trades))
        table.add_row("Winning Trades", str(m.winning_trades))
        table.add_row("Losing Trades", str(m.losing_trades))
        table.add_row("Win Rate", f"{m.win_rate * 100:.2f}%")
        table.add_row("Total Profit", f"{m.total_profit:.4f}")
        table.add_row("Total Profit %", f"{m.total_profit_pct:.2f}%")
        table.add_row("Avg Profit %", f"{m.avg_profit_pct:.2f}%")
        table.add_row("Profit Factor", f"{m.profit_factor:.2f}")
        table.add_row("Sharpe Ratio", f"{m.sharpe_ratio:.2f}")
        table.add_row("Sortino Ratio", f"{m.sortino_ratio:.2f}")
        table.add_row("Max Drawdown", f"{m.max_drawdown:.2f}%")
        table.add_row("Avg Duration", f"{m.avg_trade_duration:.1f}h")
        table.add_row("Initial Balance", f"{m.initial_balance:.2f}")
        table.add_row("Final Balance", f"{m.final_balance:.2f}")

        console.print(table)

        if export:
            console.print(f"\n[green]Results exported to: {export}[/green]")
        else:
            saved = result.save()
            console.print(f"\n[green]Results saved to: {saved}[/green]")

    except Exception as e:
        console.print(f"\n[red]Backtest error: {e}[/red]")
        logger.exception("Backtest error")
        sys.exit(1)


# ==================== Download Data Command ====================

@cli.command()
@click.option('--exchange', '-e', type=str, help='Exchange name')
@click.option('--pairs', '-p', type=str, help='Trading pairs (comma-separated or space-separated)')
@click.option('--timeframes', '-t', type=str, help='Timeframes (comma-separated)')
@click.option('--days', '-d', type=int, default=30, help='Number of days to download')
@click.option('--timerange', type=str, help='Time range (e.g., 20240101-20241231)')
@click.option('--data-format', type=str, default='json', help='Data format (json/feather/parquet)')
@click.option('--prepend', is_flag=True, help='Prepend to existing data')
@click.option('--erase', is_flag=True, help='Erase existing data')
@click.option('--config', '-c', type=str, help='Configuration file')
@click.option('--dry-run', is_flag=True, help='Show what would be downloaded without downloading')
@click.pass_context
def download_data_cmd(ctx, exchange: Optional[str], pairs: Optional[str],
                      timeframes: Optional[str], days: int, timerange: Optional[str],
                      data_format: str, prepend: bool, erase: bool,
                      config: Optional[str], dry_run: bool):
    """
    Download historical market data

    Downloads OHLCV data from the exchange for backtesting and analysis.

    Examples:
        bullseye download-data --exchange okx --pairs BTC/USDT,ETH/USDT
        bullseye download-data --exchange okx --pairs BTC/USDT ETH/USDT --timeframes 30m
        bullseye download-data --days 30 --timeframes 5m,1h
        bullseye download-data --timerange 20240101-20241231
        bullseye download-data --exchange okx --dry-run
    """
    # Import and call the actual implementation function (not the click command)
    from .commands.data_commands import _download_data_impl
    _download_data_impl(
        exchange=exchange,
        pairs=pairs,
        timeframes=timeframes,
        days=days,
        timerange=timerange,
        data_format=data_format,
        prepend=prepend,
        erase=erase,
        config=config,
        dry_run=dry_run,
    )


# ==================== Hyperopt Command ====================

@cli.command()
@click.option('--strategy', '-s', type=str, required=True, help='Strategy name')
@click.option('--epochs', type=int, default=100, help='Number of optimization epochs')
@click.option('--spaces', type=str, default='all', help='Optimization spaces (buy, sell, roi, stoploss, trailing, all)')
@click.option('--hyperopt-loss', type=str, default='DefaultHyperOptLoss',
              help='Loss function (DefaultHyperOptLoss, SharpeHyperOptLoss, SortinoHyperOptLoss, '
                   'CalmarHyperOptLoss, ProfitDrawDownHyperOptLoss, OnlyProfitHyperOptLoss, '
                   'OnlyProfitHyperOptLossDaily, MaxDrawDownHyperOptLoss, ExpectedDrawdownHyperOptLoss, '
                   'BankruptcyHyperOptLoss)')
@click.option('--min-trades', type=int, default=10, help='Minimum trades required')
@click.option('--timeframe', '-tf', type=str, help='Timeframe (e.g. 5m, 1h, 30m)')
@click.option('--timerange', type=str, help='Time range (e.g., 20240101-20241231)')
@click.option('--config', '-c', type=str, help='Configuration file')
@click.option('--stake-amount', type=float, help='Stake amount per trade')
@click.option('--initial-balance', type=float, default=1000, help='Initial balance')
@click.option('--max-open-trades', type=int, help='Max concurrent open trades')
@click.option('--fee', type=float, default=0.001, help='Fee rate')
@click.option('--export', type=str, help='Export results to JSON file')
@click.option('--random-state', type=int, help='Random seed for reproducibility')
@click.pass_context
def hyperopt(ctx, strategy: str, epochs: int, spaces: str,
             hyperopt_loss: str, min_trades: int, timeframe: str,
             timerange: Optional[str], config: Optional[str],
             stake_amount: Optional[float], initial_balance: float,
             max_open_trades: Optional[int], fee: float,
             export: Optional[str], random_state: Optional[int]):
    """
    Run hyperparameter optimization

    Examples:
        bullseye hyperopt --strategy MyStrategy --epochs 100
        bullseye hyperopt --strategy MyStrategy --hyperopt-loss SharpeHyperOptLoss --epochs 200
        bullseye hyperopt --strategy MyStrategy --spaces buy roi --epochs 500
        bullseye hyperopt --strategy MyStrategy --min-trades 20 --timerange 20240101-20241231
    """
    console.print(f"[bold green]Running hyperopt...[/bold green]")
    console.print(f"[blue]Strategy:[/blue] {strategy}")
    console.print(f"[blue]Epochs:[/blue] {epochs}")
    console.print(f"[blue]Spaces:[/blue] {spaces}")
    console.print(f"[blue]Loss function:[/blue] {hyperopt_loss}")
    console.print(f"[blue]Min trades:[/blue] {min_trades}")

    config_path = config or ctx.obj.get('config')
    try:
        from .configuration import Config
        config_obj = Config(config_path)
    except FileNotFoundError:
        config_obj = Config()

    from .optimize import HyperoptEngine

    # Convert loss function name to internal format
    loss_name = hyperopt_loss.replace('HyperOptLoss', '').replace('HyperoptLoss', '').lower()
    if loss_name == 'defaulthyperopt' or loss_name == 'default':
        loss_name = 'default'

    engine = HyperoptEngine(config=config_obj)

    try:
        engine.run(
            strategy_name=strategy,
            timeframe=timeframe,
            timerange=timerange,
            epochs=epochs,
            spaces=spaces,
            loss_function=loss_name,
            min_trades=min_trades,
            stake_amount=stake_amount,
            max_open_trades=max_open_trades,
            initial_balance=initial_balance,
            fee=fee,
            export=export,
            random_state=random_state,
        )

        best = engine.best_params
        best_metrics = engine.best_metrics

        console.print()
        console.print(Panel(
            f"[bold cyan]Best Result (loss={engine.best_loss:.6f})[/bold cyan]",
            expand=False,
        ))

        if best:
            param_table = Table(show_header=True, header_style="bold magenta")
            param_table.add_column("Parameter", style="cyan")
            param_table.add_column("Value", style="green")

            for param, value in sorted(best.items()):
                param_table.add_row(str(param), str(value))

            console.print(param_table)

        if best_metrics:
            metrics_table = Table(show_header=True, header_style="bold magenta")
            metrics_table.add_column("Metric", style="cyan")
            metrics_table.add_column("Value", style="green")

            for key, value in sorted(best_metrics.items()):
                if isinstance(value, float):
                    metrics_table.add_row(key, f"{value:.4f}")
                else:
                    metrics_table.add_row(key, str(value))

            console.print(metrics_table)

        if export:
            console.print(f"\n[green]Results exported to: {export}[/green]")
        else:
            saved = engine._export_results()
            console.print(f"\n[green]Results saved to: {saved}[/green]")

    except Exception as e:
        console.print(f"\n[red]Hyperopt error: {e}[/red]")
        logger.exception("Hyperopt error")
        sys.exit(1)


# ==================== Hyperopt List Command ====================

@cli.command()
@click.option('--best', is_flag=True, help='Show only best results')
@click.option('--profitable', is_flag=True, help='Show only profitable results')
@click.option('--export', type=str, help='Export results to file')
def hyperopt_list(best: bool, profitable: bool, export: Optional[str]):
    """
    List hyperopt results

    Examples:
        bullseye hyperopt-list
        bullseye hyperopt-list --best
        bullseye hyperopt-list --profitable
    """
    console.print("[bold green]Hyperopt Results[/bold green]")

    # Look for hyperopt results in user_data/hyperopt
    from pathlib import Path
    hyperopt_dir = Path("user_data/hyperopt")

    if not hyperopt_dir.exists():
        console.print("[yellow]No hyperopt results found.[/yellow]")
        return

    result_files = sorted(hyperopt_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)

    if not result_files:
        console.print("[yellow]No hyperopt results found.[/yellow]")
        return

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Date", style="cyan")
    table.add_column("Strategy", style="green")
    table.add_column("Loss", style="yellow")
    table.add_column("Trades", style="blue")
    table.add_column("Profit %", style="green")

    import json
    for result_file in result_files[:20]:  # Show last 20
        try:
            with open(result_file) as f:
                data = json.load(f)

            date = datetime.fromtimestamp(result_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            strategy = data.get('strategy', 'Unknown')
            loss = data.get('best_loss', 0)
            trades = data.get('best_metrics', {}).get('total_trades', 0)
            profit = data.get('best_metrics', {}).get('total_profit_pct', 0)

            if best and profit <= 0:
                continue
            if profitable and profit <= 0:
                continue

            table.add_row(
                date,
                strategy,
                f"{loss:.4f}",
                str(trades),
                f"{profit:.2f}%"
            )
        except Exception:
            continue

    console.print(table)


# ==================== Hyperopt Show Command ====================

@cli.command()
@click.option('--index', type=int, help='Result index to show')
@click.option('--file', type=str, help='Result file to show')
def hyperopt_show(index: Optional[int], file: Optional[str]):
    """
    Show hyperopt result details

    Examples:
        bullseye hyperopt-show --index 1
        bullseye hyperopt-show --file user_data/hyperopt/result_xxx.json
    """
    from pathlib import Path
    import json

    if file:
        result_file = Path(file)
    else:
        hyperopt_dir = Path("user_data/hyperopt")
        if not hyperopt_dir.exists():
            console.print("[yellow]No hyperopt results found.[/yellow]")
            return

        result_files = sorted(hyperopt_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not result_files:
            console.print("[yellow]No hyperopt results found.[/yellow]")
            return

        idx = index - 1 if index else 0
        if idx < 0 or idx >= len(result_files):
            console.print(f"[red]Invalid index. Found {len(result_files)} results.[/red]")
            return
        result_file = result_files[idx]

    try:
        with open(result_file) as f:
            data = json.load(f)

        console.print(Panel(
            f"[bold cyan]Hyperopt Result: {result_file.name}[/bold cyan]",
            expand=False,
        ))

        console.print(f"[blue]Strategy:[/blue] {data.get('strategy', 'Unknown')}")
        console.print(f"[blue]Loss:[/blue] {data.get('best_loss', 0):.6f}")
        console.print(f"[blue]Epochs:[/blue] {data.get('epochs', 0)}")

        best = data.get('best_params', {})
        if best:
            console.print("\n[bold]Best Parameters:[/bold]")
            param_table = Table(show_header=True, header_style="bold magenta")
            param_table.add_column("Parameter", style="cyan")
            param_table.add_column("Value", style="green")
            for param, value in sorted(best.items()):
                param_table.add_row(str(param), str(value))
            console.print(param_table)

        metrics = data.get('best_metrics', {})
        if metrics:
            console.print("\n[bold]Metrics:[/bold]")
            metrics_table = Table(show_header=True, header_style="bold magenta")
            metrics_table.add_column("Metric", style="cyan")
            metrics_table.add_column("Value", style="green")
            for key, value in sorted(metrics.items()):
                if isinstance(value, float):
                    metrics_table.add_row(key, f"{value:.4f}")
                else:
                    metrics_table.add_row(key, str(value))
            console.print(metrics_table)

    except Exception as e:
        console.print(f"[red]Error reading result: {e}[/red]")


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


# Register commands from commands module
cli.add_command(create_userdir)
cli.add_command(new_config)
cli.add_command(show_config)
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
