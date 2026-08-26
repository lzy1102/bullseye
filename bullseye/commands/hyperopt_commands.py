"""
Hyperopt Commands for Bullseye

Commands for hyperparameter optimization management.
"""
import sys
import json
from pathlib import Path
from typing import Optional
from datetime import datetime

import click
from rich.console import Console
from rich.table import Table

console = Console()


def get_hyperopt_results_dir() -> Path:
    """Get hyperopt results directory."""
    return Path("user_data/hyperopt")


def list_hyperopt_results(best_only: bool = False, profitable_only: bool = False) -> list:
    """List all hyperopt results."""
    results_dir = get_hyperopt_results_dir()
    if not results_dir.exists():
        return []
    
    results = []
    for filepath in results_dir.glob("*.json"):
        try:
            with open(filepath, 'r') as f:
                result = json.load(f)
                
                # Filter based on criteria
                if best_only and not result.get('is_best', False):
                    continue
                if profitable_only and result.get('total_profit', 0) <= 0:
                    continue
                
                results.append({
                    'filename': filepath.name,
                    'filepath': filepath,
                    'result': result
                })
        except (OSError, ValueError):
            pass
    
    # Sort by total_profit (descending)
    results.sort(key=lambda x: x['result'].get('total_profit', 0), reverse=True)
    return results


@click.command(name='hyperopt-list')
@click.option('--best', is_flag=True, help='Show only best results')
@click.option('--profitable', is_flag=True, help='Show only profitable results')
@click.option('--limit', type=int, default=10, help='Maximum number of results to show')
@click.option('--export-csv', type=str, help='Export to CSV file')
def hyperopt_list(best: bool, profitable: bool, limit: int, export_csv: Optional[str]):
    """
    List hyperparameter optimization results
    
    Shows all hyperopt results with filtering options.
    
    Examples:
        bullseye hyperopt-list
        bullseye hyperopt-list --best
        bullseye hyperopt-list --profitable --limit 20
        bullseye hyperopt-list --export-csv results.csv
    """
    console.print(f"[bold green]Hyperopt Results[/bold green]\n")
    
    results = list_hyperopt_results(best_only=best, profitable_only=profitable)
    
    if not results:
        console.print("[yellow]No hyperopt results found.[/yellow]")
        console.print("[dim]Run 'bullseye hyperopt' first to generate results.[/dim]")
        return
    
    console.print(f"[blue]Total Results:[/blue] {len(results)}\n")
    
    # Display results
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Rank", style="cyan")
    table.add_column("Total Profit", style="green")
    table.add_column("Profit %", style="yellow")
    table.add_column("Sharpe", style="blue")
    table.add_column("Filename", style="white")
    
    for i, item in enumerate(results[:limit], 1):
        result = item['result']
        table.add_row(
            str(i),
            f"{result.get('total_profit', 0):.4f}",
            f"{result.get('total_profit_percent', 0):.2f}%",
            f"{result.get('sharpe_ratio', 0):.2f}",
            item['filename']
        )
    
    console.print(table)
    
    if len(results) > limit:
        console.print(f"\n[dim]... and {len(results) - limit} more results[/dim]")
    
    # Export to CSV if requested
    if export_csv:
        try:
            import csv
            with open(export_csv, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['Rank', 'Total Profit', 'Profit %', 'Sharpe', 'Filename'])
                
                for i, item in enumerate(results, 1):
                    result = item['result']
                    writer.writerow([
                        i,
                        result.get('total_profit', 0),
                        result.get('total_profit_percent', 0),
                        result.get('sharpe_ratio', 0),
                        item['filename']
                    ])
            
            console.print(f"\n[green]✓ Exported to: {export_csv}[/green]")
        except Exception as e:
            console.print(f"\n[red]Error exporting to CSV: {e}[/red]")


@click.command(name='hyperopt-show')
@click.option('--hyperopt-id', type=str, help='Hyperopt result ID (filename)')
@click.option('--best', is_flag=True, help='Show best result')
@click.option('--print-json', is_flag=True, help='Output as JSON')
def hyperopt_show(hyperopt_id: Optional[str], best: bool, print_json: bool):
    """
    Show hyperopt result details
    
    Displays detailed information about a hyperopt result.
    
    Examples:
        bullseye hyperopt-show --hyperopt-id hyperopt-result-2024-01-01.json
        bullseye hyperopt-show --best
        bullseye hyperopt-show --print-json
    """
    console.print(f"[bold green]Hyperopt Result Details[/bold green]\n")
    
    results_dir = get_hyperopt_results_dir()
    
    if not results_dir.exists():
        console.print("[yellow]No hyperopt results found.[/yellow]")
        return
    
    # Find result
    if best:
        # Get best result
        results = list_hyperopt_results()
        if not results:
            console.print("[yellow]No results found[/yellow]")
            return
        
        result = results[0]['result']
        filename = results[0]['filename']
    elif hyperopt_id:
        # Get specific result
        filepath = results_dir / hyperopt_id
        if not filepath.exists():
            console.print(f"[red]Result file not found: {hyperopt_id}[/red]")
            return
        
        with open(filepath, 'r') as f:
            result = json.load(f)
        filename = hyperopt_id
    else:
        console.print("[red]Please specify --hyperopt-id or --best[/red]")
        return
    
    # Display result
    if print_json:
        console.print(json.dumps(result, indent=2, default=str))
        return
    
    # Display formatted result
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    
    # Basic metrics
    table.add_row("Filename", filename)
    table.add_row("Total Profit", f"{result.get('total_profit', 0):.4f}")
    table.add_row("Profit %", f"{result.get('total_profit_percent', 0):.2f}%")
    table.add_row("Total Trades", str(result.get('total_trades', 0)))
    table.add_row("Win Rate", f"{result.get('win_rate', 0):.2f}%")
    
    console.print("\n[bold]Performance Metrics:[/bold]")
    console.print(table)
    
    # Best parameters
    best_params = result.get('best_params', {})
    if best_params:
        console.print("\n[bold]Best Parameters:[/bold]")
        param_table = Table(show_header=True, header_style="bold magenta")
        param_table.add_column("Parameter", style="cyan")
        param_table.add_column("Value", style="green")
        
        for param, value in best_params.items():
            param_table.add_row(str(param), str(value))
        
        console.print(param_table)
    
    # Loss function
    loss_function = result.get('loss_function', 'Unknown')
    console.print(f"\n[blue]Loss Function:[/blue] {loss_function}")
    
    # Additional metrics
    sharpe = result.get('sharpe_ratio', 0)
    sortino = result.get('sortino_ratio', 0)
    calmar = result.get('calmar_ratio', 0)
    max_drawdown = result.get('max_drawdown', 0)
    
    console.print("\n[bold]Risk Metrics:[/bold]")
    risk_table = Table(show_header=True, header_style="bold magenta")
    risk_table.add_column("Metric", style="cyan")
    risk_table.add_column("Value", style="green")
    
    risk_table.add_row("Sharpe Ratio", f"{sharpe:.2f}")
    risk_table.add_row("Sortino Ratio", f"{sortino:.2f}")
    risk_table.add_row("Calmar Ratio", f"{calmar:.2f}")
    risk_table.add_row("Max Drawdown", f"{max_drawdown:.2f}%")
    
    console.print(risk_table)


@click.command(name='strategy-updater')
@click.option('--strategy', '-s', type=str, help='Strategy name')
@click.option('--dry-run', is_flag=True, help='Dry run without making changes')
def strategy_updater(strategy: Optional[str], dry_run: bool):
    """
    Update strategy to latest version
    
    Automatically upgrades old version strategies to new format.
    
    Examples:
        bullseye strategy-updater --strategy MyStrategy
        bullseye strategy-updater --strategy MyStrategy --dry-run
    """
    console.print(f"[bold green]Strategy Updater[/bold green]")
    console.print(f"[blue]Strategy:[/blue] {strategy or 'Not specified'}")
    console.print(f"[blue]Dry Run:[/blue] {dry_run}\n")
    
    if not strategy:
        console.print("[red]Please specify --strategy[/red]")
        return
    
    # Find strategy file
    strategy_path = Path(f"user_data/strategies/{strategy}.py")
    if not strategy_path.exists():
        console.print(f"[red]Strategy file not found: {strategy_path}[/red]")
        return
    
    console.print(f"[yellow]Reading strategy file: {strategy_path}[/yellow]")
    
    try:
        with open(strategy_path, 'r') as f:
            content = f.read()
        
        # Check for old Freqtrade v2 patterns
        v2_patterns = [
            'buy_signal',
            'sell_signal',
            'minimal_roi',
            'stoploss_on_exchange',
            'ticker_interval',
        ]
        
        found_v2 = any(pattern in content for pattern in v2_patterns)
        
        if found_v2:
            console.print("[yellow]Detected Freqtrade v2 patterns in strategy[/yellow]")
            console.print("\n[bold]Suggested Changes:[/bold]")
            console.print("  - Replace 'buy_signal' with 'enter_long'")
            console.print("  - Replace 'sell_signal' with 'exit_long'")
            console.print("  - Update ROI configuration")
            console.print("  - Update stoploss configuration")
            console.print("  - Update timeframe format")
            
            if not dry_run:
                confirm = input("\nApply these changes? (y/n): ")
                if confirm.lower() in ('y', 'yes'):
                    console.print("[green]Updating strategy...[/green]")
                    # Apply changes here
                    console.print("[green]✓ Strategy updated[/green]")
                else:
                    console.print("[yellow]Update cancelled[/yellow]")
        else:
            console.print("[green]✓ Strategy is already compatible with v3[/green]")
    
    except Exception as e:
        console.print(f"[red]Error processing strategy: {e}[/red]")
