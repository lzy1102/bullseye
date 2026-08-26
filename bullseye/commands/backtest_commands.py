"""
Backtesting Commands for Bullseye

Commands for backtesting analysis and result management.
"""
import sys
import json
from pathlib import Path
from typing import Optional
from datetime import datetime

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

# Default backtest results directory
BACKTEST_RESULTS_DIR = Path("user_data/backtest_results")


def get_backtest_results_dir() -> Path:
    """Get backtest results directory."""
    BACKTEST_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    return BACKTEST_RESULTS_DIR


def load_backtest_result(filename: str) -> Optional[dict]:
    """Load a backtest result file."""
    filepath = get_backtest_results_dir() / filename
    if not filepath.exists():
        return None

    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception as e:
        console.print(f"[red]Error loading {filename}: {e}[/red]")
        return None


def list_backtest_results() -> list:
    """List all backtest result files."""
    results_dir = get_backtest_results_dir()
    if not results_dir.exists():
        return []

    results = []
    for filepath in results_dir.glob("*.json"):
        try:
            stat = filepath.stat()
            results.append({
                'filename': filepath.name,
                'filepath': filepath,
                'size': stat.st_size,
                'modified': datetime.fromtimestamp(stat.st_mtime)
            })
        except OSError:
            pass

    # Sort by modification time (newest first)
    results.sort(key=lambda x: x['modified'], reverse=True)
    return results


@click.command(name='backtesting-show')
@click.option('--export-filename', type=str, help='Specific result file to show')
@click.option('--show-all', is_flag=True, help='Show all results')
@click.option('--print-json', is_flag=True, help='Output as JSON')
def backtesting_show(export_filename: Optional[str], show_all: bool, print_json: bool):
    """
    Show backtesting results
    
    Displays historical backtesting results.
    
    Examples:
        bullseye backtesting-show
        bullseye backtesting-show --export-filename backtest-result-2024-01-01.json
        bullseye backtesting-show --show-all
    """
    if export_filename:
        # Show specific result
        result = load_backtest_result(export_filename)
        if not result:
            console.print(f"[red]Backtest result not found: {export_filename}[/red]")
            sys.exit(1)

        if print_json:
            console.print(json.dumps(result, indent=2, default=str))
            return

        # Display result
        console.print(f"[bold green]Backtest Result: {export_filename}[/bold green]\n")
        _display_backtest_result(result)

    else:
        # List all results
        results = list_backtest_results()

        if not results:
            console.print("[yellow]No backtest results found.[/yellow]")
            console.print("[dim]Run 'bullseye backtesting' first.[/dim]")
            return

        if print_json:
            output = [{
                'filename': r['filename'],
                'size_bytes': r['size'],
                'modified': r['modified'].isoformat()
            } for r in results]
            console.print(json.dumps(output, indent=2))
            return

        console.print("[bold green]Backtest Results[/bold green]\n")

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Filename", style="cyan")
        table.add_column("Size", style="green")
        table.add_column("Modified", style="blue")

        for r in results[:20]:  # Show last 20
            size_str = f"{r['size'] / 1024:.1f} KB" if r['size'] < 1024*1024 else f"{r['size'] / (1024*1024):.1f} MB"
            table.add_row(
                r['filename'],
                size_str,
                r['modified'].strftime('%Y-%m-%d %H:%M')
            )

        console.print(table)

        if len(results) > 20:
            console.print(f"\n[dim]... and {len(results) - 20} more results[/dim]")

        console.print("\n[yellow]View details:[/yellow] bullseye backtesting-show --export-filename <filename>")


def _display_backtest_result(result: dict):
    """Display a backtest result in a formatted way."""
    # Strategy info
    strategy = result.get('strategy', 'Unknown')
    console.print(Panel(f"[bold cyan]Strategy: {strategy}[/bold cyan]", expand=False))

    # Performance metrics
    metrics = result.get('metrics', {})

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Total Profit", f"{metrics.get('total_profit', 0):.4f}")
    table.add_row("Total Profit %", f"{metrics.get('total_profit_percent', 0):.2f}%")
    table.add_row("Win Rate", f"{metrics.get('win_rate', 0):.2f}%")
    table.add_row("Profit Factor", f"{metrics.get('profit_factor', 0):.2f}")
    table.add_row("Sharpe Ratio", f"{metrics.get('sharpe_ratio', 0):.2f}")
    table.add_row("Max Drawdown", f"{metrics.get('max_drawdown', 0):.2f}%")
    table.add_row("Total Trades", str(metrics.get('total_trades', 0)))

    console.print("\n[bold]Performance Metrics:[/bold]")
    console.print(table)

    # Trade statistics
    trades = result.get('trades', [])
    if trades:
        console.print(f"\n[bold]Trades:[/bold] {len(trades)} total")

        winning_trades = [t for t in trades if t.get('profit', 0) > 0]
        losing_trades = [t for t in trades if t.get('profit', 0) <= 0]

        console.print(f"  [green]Winning: {len(winning_trades)}[/green]")
        console.print(f"  [red]Losing: {len(losing_trades)}[/red]")


@click.command(name='backtesting-analysis')
@click.option('--export-filename', type=str, required=True, help='Backtest result file to analyze')
@click.option('--analysis-groups', type=str, default='entry_tag,exit_tag,pair',
              help='Groups to analyze (comma-separated)')
@click.option('--export-csv', type=str, help='Export analysis to CSV file')
@click.option('--print-json', is_flag=True, help='Output as JSON')
def backtesting_analysis(export_filename: str, analysis_groups: str,
                         export_csv: Optional[str], print_json: bool):
    """
    Analyze backtesting results
    
    Performs detailed analysis of backtest results by entry/exit tags,
    trading pairs, and other dimensions.
    
    Examples:
        bullseye backtesting-analysis --export-filename backtest-result.json
        bullseye backtesting-analysis --export-filename backtest-result.json --analysis-groups entry_tag,pair
        bullseye backtesting-analysis --export-filename backtest-result.json --export-csv analysis.csv
    """
    result = load_backtest_result(export_filename)
    if not result:
        console.print(f"[red]Backtest result not found: {export_filename}[/red]")
        sys.exit(1)

    trades = result.get('trades', [])
    if not trades:
        console.print("[yellow]No trades found in backtest result.[/yellow]")
        return

    console.print("[bold green]Backtest Analysis[/bold green]")
    console.print(f"[blue]File:[/blue] {export_filename}")
    console.print(f"[blue]Trades:[/blue] {len(trades)}\n")

    groups = [g.strip() for g in analysis_groups.split(',')]
    analysis_results = {}

    for group in groups:
        if group == 'entry_tag':
            analysis_results['entry_tag'] = _analyze_by_entry_tag(trades)
        elif group == 'exit_tag':
            analysis_results['exit_tag'] = _analyze_by_exit_tag(trades)
        elif group == 'pair':
            analysis_results['pair'] = _analyze_by_pair(trades)

    if print_json:
        console.print(json.dumps(analysis_results, indent=2, default=str))
        return

    # Display analysis
    for group_name, group_data in analysis_results.items():
        console.print(f"\n[bold cyan]Analysis by {group_name.replace('_', ' ').title()}:[/bold cyan]")

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column(group_name.replace('_', ' ').title(), style="cyan")
        table.add_column("Trades", style="white")
        table.add_column("Win Rate", style="green")
        table.add_column("Avg Profit %", style="blue")
        table.add_column("Total Profit %", style="yellow")

        for key, stats in sorted(group_data.items(), key=lambda x: x[1]['total_profit'], reverse=True):
            win_rate = (stats['wins'] / stats['total'] * 100) if stats['total'] > 0 else 0
            avg_profit = stats['total_profit'] / stats['total'] if stats['total'] > 0 else 0

            table.add_row(
                str(key),
                str(stats['total']),
                f"{win_rate:.1f}%",
                f"{avg_profit:.2f}%",
                f"{stats['total_profit']:.2f}%"
            )

        console.print(table)

    # Export to CSV if requested
    if export_csv:
        try:
            import csv
            with open(export_csv, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['Group', 'Key', 'Trades', 'Wins', 'Losses', 'Win Rate %', 'Total Profit %'])

                for group_name, group_data in analysis_results.items():
                    for key, stats in group_data.items():
                        win_rate = (stats['wins'] / stats['total'] * 100) if stats['total'] > 0 else 0
                        writer.writerow([
                            group_name,
                            key,
                            stats['total'],
                            stats['wins'],
                            stats['losses'],
                            f"{win_rate:.2f}",
                            f"{stats['total_profit']:.4f}"
                        ])

            console.print(f"\n[green]✓ Analysis exported to: {export_csv}[/green]")
        except Exception as e:
            console.print(f"\n[red]Error exporting to CSV: {e}[/red]")


def _analyze_by_entry_tag(trades: list) -> dict:
    """Analyze trades by entry tag."""
    stats = {}

    for trade in trades:
        tag = trade.get('entry_tag', 'unknown')
        if tag not in stats:
            stats[tag] = {'total': 0, 'wins': 0, 'losses': 0, 'total_profit': 0}

        stats[tag]['total'] += 1
        profit = trade.get('profit', 0)
        stats[tag]['total_profit'] += profit

        if profit > 0:
            stats[tag]['wins'] += 1
        else:
            stats[tag]['losses'] += 1

    return stats


def _analyze_by_exit_tag(trades: list) -> dict:
    """Analyze trades by exit tag."""
    stats = {}

    for trade in trades:
        tag = trade.get('exit_tag', 'unknown')
        if tag not in stats:
            stats[tag] = {'total': 0, 'wins': 0, 'losses': 0, 'total_profit': 0}

        stats[tag]['total'] += 1
        profit = trade.get('profit', 0)
        stats[tag]['total_profit'] += profit

        if profit > 0:
            stats[tag]['wins'] += 1
        else:
            stats[tag]['losses'] += 1

    return stats


def _analyze_by_pair(trades: list) -> dict:
    """Analyze trades by trading pair."""
    stats = {}

    for trade in trades:
        pair = trade.get('pair', 'unknown')
        if pair not in stats:
            stats[pair] = {'total': 0, 'wins': 0, 'losses': 0, 'total_profit': 0}

        stats[pair]['total'] += 1
        profit = trade.get('profit', 0)
        stats[pair]['total_profit'] += profit

        if profit > 0:
            stats[pair]['wins'] += 1
        else:
            stats[pair]['losses'] += 1

    return stats
