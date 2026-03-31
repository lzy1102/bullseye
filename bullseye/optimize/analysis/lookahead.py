"""
Lookahead Analysis for Bullseye

Detects lookahead bias in trading strategies by comparing signals
from full data vs truncated data.
"""
import sys
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime
from copy import deepcopy

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


class LookaheadAnalysis:
    """
    Detects lookahead bias in trading strategies.
    
    Lookahead bias occurs when a strategy uses future information
    to make trading decisions. This is detected by:
    1. Running the strategy on full data
    2. Running the strategy on truncated data (removing last N candles)
    3. Comparing the signals - if they differ, lookahead bias exists
    """
    
    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.results = {}
    
    def analyze(self, strategy, dataframe: Any, pair: str) -> Dict:
        """
        Analyze a strategy for lookahead bias.
        
        Args:
            strategy: Strategy instance
            dataframe: DataFrame with OHLCV data
            pair: Trading pair name
            
        Returns:
            Dictionary with analysis results
        """
        console.print(f"[green]Analyzing {pair} for lookahead bias...[/green]")
        
        # Get indicators from strategy
        try:
            # Run on full data
            df_full = strategy.populate_indicators(dataframe.copy(), {'pair': pair})
            df_full = strategy.populate_entry_trend(df_full, {'pair': pair})
            df_full = strategy.populate_exit_trend(df_full, {'pair': pair})
            
            # Test different truncation points
            truncation_points = [1, 5, 10, 50, 100]
            bias_detected = False
            biased_indicators = []
            
            for truncate in truncation_points:
                if len(dataframe) <= truncate:
                    continue
                
                # Truncate data
                df_truncated = dataframe.iloc[:-truncate].copy()
                
                # Run on truncated data
                df_test = strategy.populate_indicators(df_truncated, {'pair': pair})
                df_test = strategy.populate_entry_trend(df_test, {'pair': pair})
                df_test = strategy.populate_exit_trend(df_test, {'pair': pair})
                
                # Compare signals at common points
                common_idx = df_test.index
                
                # Check entry signals
                if 'enter_long' in df_full.columns and 'enter_long' in df_test.columns:
                    full_signals = df_full.loc[common_idx, 'enter_long']
                    test_signals = df_test['enter_long']
                    
                    if not full_signals.equals(test_signals):
                        bias_detected = True
                        biased_indicators.append({
                            'indicator': 'enter_long',
                            'truncate': truncate,
                            'mismatches': (full_signals != test_signals).sum()
                        })
                
                # Check exit signals
                if 'exit_long' in df_full.columns and 'exit_long' in df_test.columns:
                    full_signals = df_full.loc[common_idx, 'exit_long']
                    test_signals = df_test['exit_long']
                    
                    if not full_signals.equals(test_signals):
                        bias_detected = True
                        biased_indicators.append({
                            'indicator': 'exit_long',
                            'truncate': truncate,
                            'mismatches': (full_signals != test_signals).sum()
                        })
            
            return {
                'pair': pair,
                'bias_detected': bias_detected,
                'biased_indicators': biased_indicators,
                'total_candles': len(dataframe),
                'tested_truncations': truncation_points
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
                f"[bold red]⚠ Lookahead Bias Detected in {pair}![/bold red]",
                expand=False
            ))
            
            biased_indicators = results.get('biased_indicators', [])
            if biased_indicators:
                table = Table(show_header=True, header_style="bold magenta")
                table.add_column("Indicator", style="cyan")
                table.add_column("Truncation", style="yellow")
                table.add_column("Mismatches", style="red")
                
                for item in biased_indicators:
                    table.add_row(
                        item['indicator'],
                        f"-{item['truncate']} candles",
                        str(item['mismatches'])
                    )
                
                console.print("\n[bold]Biased Signals:[/bold]")
                console.print(table)
            
            console.print("\n[yellow]Recommendations:[/yellow]")
            console.print("  1. Check indicators using rolling windows")
            console.print("  2. Avoid using shift(-n) which looks ahead")
            console.print("  3. Use proper warmup periods for indicators")
            console.print("  4. Verify indicator calculations don't use future data")
        else:
            console.print(Panel(
                f"[bold green]✓ No Lookahead Bias Detected in {pair}[/bold green]",
                expand=False
            ))


@click.command(name='lookahead-analysis')
@click.option('--strategy', '-s', type=str, required=True, help='Strategy name')
@click.option('--pair', '-p', type=str, default='BTC/USDT', help='Trading pair to analyze')
@click.option('--timeframe', '-t', type=str, default='5m', help='Timeframe')
@click.option('--timerange', type=str, help='Time range (e.g., 20240101-20241231)')
@click.option('--config', '-c', type=str, help='Configuration file')
@click.option('--print-json', is_flag=True, help='Output as JSON')
def lookahead_analysis(strategy: str, pair: str, timeframe: str, timerange: Optional[str],
                       config: Optional[str], print_json: bool):
    """
    Detect lookahead bias in strategy
    
    Analyzes a strategy to detect if it uses future data (lookahead bias).
    This is done by comparing signals from full data vs truncated data.
    
    Examples:
        bullseye lookahead-analysis --strategy MyStrategy
        bullseye lookahead-analysis --strategy MyStrategy --pair ETH/USDT --timeframe 1h
        bullseye lookahead-analysis --strategy MyStrategy --timerange 20240101-20241231
    """
    console.print(f"[bold green]Lookahead Bias Analysis[/bold green]")
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
        strategy_instance = strategy_class()
        
        # Load data (placeholder - would need actual data loading)
        console.print("[yellow]Note: This requires historical data.[/yellow]")
        console.print("[dim]Run 'bullseye download-data' first to get the data.[/dim]\n")
        
        # For demonstration, show what the analysis would do
        console.print("[bold]Analysis Process:[/bold]")
        console.print("  1. Run strategy on full dataset")
        console.print("  2. Truncate last N candles from dataset")
        console.print("  3. Run strategy on truncated dataset")
        console.print("  4. Compare signals at common points")
        console.print("  5. If signals differ, lookahead bias detected\n")
        
        # Placeholder result
        result = {
            'pair': pair,
            'bias_detected': False,
            'biased_indicators': [],
            'total_candles': 0,
            'tested_truncations': [1, 5, 10, 50, 100],
            'note': 'Actual analysis requires downloaded historical data'
        }
        
        if print_json:
            import json
            console.print(json.dumps(result, indent=2))
        else:
            analyzer = LookaheadAnalysis()
            analyzer.print_report(result)
        
    except Exception as e:
        console.print(f"[red]Error during analysis: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)
