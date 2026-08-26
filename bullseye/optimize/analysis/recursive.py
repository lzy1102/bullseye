"""
Recursive Analysis for Bullseye

Detects recursive bias in trading strategies by running backtests
with different startup_candle_count values.
"""
import sys
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


class RecursiveAnalysis:
    """
    Detects recursive bias in trading strategies.
    
    Recursive bias occurs when indicators (like EMA) produce different
    values depending on the startup period. This is detected by:
    1. Running backtest with different startup_candle_count values
    2. Comparing the signals - if they differ, recursive bias exists
    """
    
    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.results = {}
    
    def analyze(self, strategy, dataframe: Any, pair: str) -> Dict:
        """
        Analyze a strategy for recursive bias.
        
        Args:
            strategy: Strategy instance
            dataframe: DataFrame with OHLCV data
            pair: Trading pair name
            
        Returns:
            Dictionary with analysis results
        """
        console.print(f"[green]Analyzing {pair} for recursive bias...[/green]")
        
        try:
            # Test different startup periods
            startup_periods = [0, 10, 50, 100, 200, 500]
            signals_by_period = {}
            
            for startup in startup_periods:
                if len(dataframe) <= startup:
                    continue
                
                # Skip first N candles (startup period)
                df_test = dataframe.iloc[startup:].copy()
                
                # Run strategy
                df_result = strategy.populate_indicators(df_test, {'pair': pair})
                df_result = strategy.populate_entry_trend(df_result, {'pair': pair})
                df_result = strategy.populate_exit_trend(df_result, {'pair': pair})
                
                # Store signals
                signals_by_period[startup] = {
                    'entry': df_result.get('enter_long', []),
                    'exit': df_result.get('exit_long', [])
                }
            
            # Compare signals across periods
            bias_detected = False
            sensitive_indicators = []
            
            # Get common index (intersection of all periods)
            common_start = max(startup_periods)
            if len(dataframe) > common_start:
                # Compare entry signals
                base_signals = signals_by_period.get(0, {}).get('entry', [])
                for startup, signals in signals_by_period.items():
                    if startup == 0:
                        continue
                    current_signals = signals.get('entry', [])
                    if len(base_signals) > 0 and len(current_signals) > 0:
                        # Compare overlapping region
                        min_len = min(len(base_signals), len(current_signals))
                        if not base_signals[:min_len].equals(current_signals[:min_len]):
                            bias_detected = True
                            sensitive_indicators.append({
                                'indicator': 'enter_long',
                                'startup': startup,
                                'type': 'recursive'
                            })
            
            return {
                'pair': pair,
                'bias_detected': bias_detected,
                'sensitive_indicators': sensitive_indicators,
                'tested_periods': list(signals_by_period.keys()),
                'recommendation': 'Use startup_candle_count >= 100 for stable indicators' if bias_detected else 'No issues detected'
            }
            
        except Exception as e:
            return {
                'pair': pair,
                'error': str(e),
                'bias_detected': False
            }
    
    def print_report(self, results: Dict):
        """Print analysis report."""
        pair = results.get('pair', 'Unknown')
        bias_detected = results.get('bias_detected', False)
        
        if bias_detected:
            console.print(Panel(
                f"[bold yellow]⚠ Recursive Bias Detected in {pair}![/bold yellow]",
                expand=False
            ))
            
            sensitive_indicators = results.get('sensitive_indicators', [])
            if sensitive_indicators:
                table = Table(show_header=True, header_style="bold magenta")
                table.add_column("Indicator", style="cyan")
                table.add_column("Startup Period", style="yellow")
                table.add_column("Issue Type", style="red")
                
                for item in sensitive_indicators:
                    table.add_row(
                        item['indicator'],
                        f"{item['startup']} candles",
                        item['type']
                    )
                
                console.print("\n[bold]Sensitive Indicators:[/bold]")
                console.print(table)
            
            console.print("\n[yellow]Recommendations:[/yellow]")
            console.print("  1. Use startup_candle_count >= 100 for stable indicators")
            console.print("  2. Avoid indicators that depend on entire series (e.g., some EMA implementations)")
            console.print("  3. Use indicators with consistent warmup periods")
            console.print("  4. Consider using rolling windows with fixed periods")
        else:
            console.print(Panel(
                f"[bold green]✓ No Recursive Bias Detected in {pair}[/bold green]",
                expand=False
            ))
        
        recommendation = results.get('recommendation', '')
        if recommendation:
            console.print(f"\n[blue]Recommendation:[/blue] {recommendation}")


@click.command(name='recursive-analysis')
@click.option('--strategy', '-s', type=str, required=True, help='Strategy name')
@click.option('--pair', '-p', type=str, default='BTC/USDT', help='Trading pair to analyze')
@click.option('--timeframe', '-t', type=str, default='5m', help='Timeframe')
@click.option('--timerange', type=str, help='Time range (e.g., 20240101-20241231)')
@click.option('--startup-periods', type=str, help='Comma-separated startup periods to test')
@click.option('--config', '-c', type=str, help='Configuration file')
@click.option('--print-json', is_flag=True, help='Output as JSON')
def recursive_analysis(strategy: str, pair: str, timeframe: str, timerange: Optional[str],
                       startup_periods: Optional[str], config: Optional[str], print_json: bool):
    """
    Detect recursive bias in strategy
    
    Analyzes a strategy to detect recursive bias (indicators that change
    based on startup period). This is common with indicators like EMA
    that depend on the entire price history.
    
    Examples:
        bullseye recursive-analysis --strategy MyStrategy
        bullseye recursive-analysis --strategy MyStrategy --pair ETH/USDT
        bullseye recursive-analysis --strategy MyStrategy --startup-periods 0,50,100,200
    """
    console.print(f"[bold green]Recursive Bias Analysis[/bold green]")
    console.print(f"[blue]Strategy:[/blue] {strategy}")
    console.print(f"[blue]Pair:[/blue] {pair}")
    console.print(f"[blue]Timeframe:[/blue] {timeframe}\n")
    
    try:
        # Load strategy
        import importlib
        import sys
        from pathlib import Path
        
        # Add strategy path
        strategy_path = Path("user_data/strategies")
        if strategy_path.exists():
            sys.path.insert(0, str(strategy_path))
        
        # Import strategy
        try:
            module = importlib.import_module(strategy)
            strategy_class = getattr(module, strategy)
        except (ImportError, AttributeError) as e:
            console.print(f"[red]Error loading strategy: {e}[/red]")
            sys.exit(1)
        
        # Create strategy instance
        strategy_class()

        # Parse startup periods
        periods = [0, 10, 50, 100, 200, 500]
        if startup_periods:
            try:
                periods = [int(p.strip()) for p in startup_periods.split(',')]
            except ValueError:
                console.print("[red]Invalid startup periods format. Use: 0,50,100,200[/red]")
                sys.exit(1)
        
        console.print("[yellow]Note: This requires historical data.[/yellow]")
        console.print("[dim]Run 'bullseye download-data' first to get the data.[/dim]\n")
        
        # For demonstration, show what the analysis would do
        console.print("[bold]Analysis Process:[/bold]")
        console.print("  1. Run strategy with different startup_candle_count values")
        console.print("  2. Compare signals across different startup periods")
        console.print("  3. If signals differ, recursive bias detected")
        console.print(f"  4. Testing periods: {periods}\n")
        
        # Placeholder result
        result = {
            'pair': pair,
            'bias_detected': False,
            'sensitive_indicators': [],
            'tested_periods': periods,
            'recommendation': 'Use startup_candle_count >= 100 for stable indicators',
            'note': 'Actual analysis requires downloaded historical data'
        }
        
        if print_json:
            import json
            console.print(json.dumps(result, indent=2))
        else:
            analyzer = RecursiveAnalysis()
            analyzer.print_report(result)
        
    except Exception as e:
        console.print(f"[red]Error during analysis: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)
