"""
Plot Commands for Bullseye

Commands for visualizing backtesting results and trading data.
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


@click.command(name='plot-dataframe')
@click.option('--pair', '-p', type=str, help='Trading pair')
@click.option('--timeframe', '-tf', type=str, help='Timeframe')
@click.option('--timerange', type=str, help='Time range (e.g., 20240101-20241231)')
@click.option('--indicators', type=str, help='Indicators to plot (comma-separated)')
@click.option('--plot-limit', type=int, default=100, help='Number of candles to plot')
@click.option('--trade-source', type=str, help='Source of trade data (backtest/database)')
@click.option('--export-filename', type=str, help='Backtest result file')
@click.option('--output', '-o', type=str, help='Output HTML file path')
def plot_dataframe(pair: Optional[str], timeframe: Optional[str], timerange: Optional[str],
                 indicators: Optional[str], plot_limit: int, trade_source: Optional[str],
                 export_filename: Optional[str], output: Optional[str]):
    """
    Plot K-line and indicators
    
    Creates an interactive HTML chart with OHLCV data and indicators.
    
    Examples:
        bullseye plot-dataframe --pair BTC/USDT --timeframe 5m
        bullseye plot-dataframe --export-filename backtest-result.json --indicators rsi,ema
        bullseye plot-dataframe --plot-limit 200 --output chart.html
    """
    console.print(f"[bold green]Plotting Dataframe[/bold green]")
    console.print(f"[blue]Pair:[/blue] {pair or 'Not specified'}")
    console.print(f"[blue]Timeframe:[/blue] {timeframe or 'Not specified'}")
    console.print(f"[blue]Plot Limit:[/blue] {plot_limit} candles\n")
    
    try:
        import pandas as pd
    except ImportError:
        console.print("[red]Pandas not installed. Install with: pip install pandas[/red]")
        sys.exit(1)
    
    try:
        import plotly.graph_objects as go
        import plotly.express as px
    except ImportError:
        console.print("[yellow]Plotly not installed. Install with: pip install plotly kaleido[/yellow]")
        console.print("[dim]Will use basic text output instead.[/dim]\n")
        
        # Show basic data info
        if export_filename:
            result_file = Path(export_filename)
            if result_file.exists():
                with open(result_file, 'r') as f:
                    result = json.load(f)
                    trades = result.get('trades', [])
                    console.print(f"[bold]Trades:[/bold] {len(trades)}")
                    if trades:
                        table = Table(show_header=True, header_style="bold magenta")
                        table.add_column("Pair", style="cyan")
                        table.add_column("Entry Time", style="green")
                        table.add_column("Exit Time", style="blue")
                        table.add_column("Profit %", style="yellow")
                        
                        for trade in trades[:10]:
                            table.add_row(
                                trade.get('pair', 'N/A'),
                                trade.get('open_date', 'N/A'),
                                trade.get('close_date', 'N/A'),
                                f"{trade.get('profit_percent', 0):.2f}%"
                            )
                        console.print(table)
        return
    
    # Load data
    if export_filename:
        result_file = Path(export_filename)
        if not result_file.exists():
            console.print(f"[red]Backtest result file not found: {export_filename}[/red]")
            sys.exit(1)
        
        with open(result_file, 'r') as f:
            result = json.load(f)
            trades = result.get('trades', [])
            
            if not trades:
                console.print("[yellow]No trades found in backtest result[/yellow]")
                return
            
            # Create DataFrame from trades
            df = pd.DataFrame(trades)
            
            # Convert date strings to datetime
            if 'open_date' in df.columns:
                df['open_date'] = pd.to_datetime(df['open_date'])
            if 'close_date' in df.columns:
                df['close_date'] = pd.to_datetime(df['close_date'])
            
            console.print(f"[blue]Loaded:[/blue] {len(df)} trades")
    else:
        console.print("[yellow]No data source specified. Use --export-filename or provide data.[/yellow]")
        return
    
    # Create candlestick chart
    fig = go.Figure()
    
    # Add candlestick
    if 'open_rate' in df.columns and 'high_rate' in df.columns and 'low_rate' in df.columns and 'close_rate' in df.columns:
        fig.add_trace(go.Candlestick(
            x=df.index,
            open=df['open_rate'],
            high=df['high_rate'],
            low=df['low_rate'],
            close=df['close_rate'],
            name='OHLCV'
        ))
    
    # Add indicators
    if indicators:
        indicator_list = [ind.strip() for ind in indicators.split(',')]
        for indicator in indicator_list:
            if indicator in df.columns:
                fig.add_trace(go.Scatter(
                    x=df.index,
                    y=df[indicator],
                    mode='lines',
                    name=indicator,
                    line=dict(color='rgba(0,0,255,0.5)')
                ))
    
    # Add entry/exit markers
    if 'enter_long' in df.columns:
        entry_points = df[df['enter_long'] == 1]
        if not entry_points.empty:
            fig.add_trace(go.Scatter(
                x=entry_points.index,
                y=entry_points['close_rate'],
                mode='markers',
                name='Entry',
                marker=dict(symbol='triangle-up', size=10, color='green')
            ))
    
    if 'exit_long' in df.columns:
        exit_points = df[df['exit_long'] == 1]
        if not exit_points.empty:
            fig.add_trace(go.Scatter(
                x=exit_points.index,
                y=exit_points['close_rate'],
                mode='markers',
                name='Exit',
                marker=dict(symbol='triangle-down', size=10, color='red')
            ))
    
    fig.update_layout(
        title=f"{pair or 'Trading'} - {timeframe or 'Dataframe'}",
        xaxis_title='Time',
        yaxis_title='Price',
        template='plotly_dark',
        height=600,
        xaxis_rangeslider=dict(visible=False)
    )
    
    # Save to HTML
    output_path = output or 'plot_dataframe.html'
    fig.write_html(output_path)
    console.print(f"\n[green]✓ Plot saved to: {output_path}[/green]")


@click.command(name='plot-profit')
@click.option('--export-filename', type=str, help='Backtest result file')
@click.option('--timerange', type=str, help='Time range (e.g., 20240101-20241231)')
@click.option('--output', '-o', type=str, help='Output HTML file path')
def plot_profit(export_filename: Optional[str], timerange: Optional[str], output: Optional[str]):
    """
    Plot profit curve
    
    Creates an interactive HTML chart showing cumulative profit over time.
    
    Examples:
        bullseye plot-profit --export-filename backtest-result.json
        bullseye plot-profit --export-filename backtest-result.json --output profit.html
    """
    console.print(f"[bold green]Plotting Profit Curve[/bold green]\n")
    
    if not export_filename:
        console.print("[red]Please specify --export-filename[/red]")
        sys.exit(1)
    
    try:
        import pandas as pd
        import plotly.graph_objects as go
    except ImportError:
        console.print("[red]Pandas or Plotly not installed. Install with: pip install pandas plotly kaleido[/red]")
        sys.exit(1)
    
    # Load backtest result
    result_file = Path(export_filename)
    if not result_file.exists():
        console.print(f"[red]Backtest result file not found: {export_filename}[/red]")
        sys.exit(1)
    
    with open(result_file, 'r') as f:
        result = json.load(f)
        trades = result.get('trades', [])
        
        if not trades:
            console.print("[yellow]No trades found in backtest result[/yellow]")
            return
    
    # Create DataFrame
    df = pd.DataFrame(trades)
    
    # Convert date strings to datetime
    if 'close_date' in df.columns:
        df['close_date'] = pd.to_datetime(df['close_date'])
    
    # Calculate cumulative profit
    df = df.sort_values('close_date')
    df['cumulative_profit'] = df['profit'].cumsum()
    df['cumulative_profit_percent'] = (df['cumulative_profit'] / df['cumulative_profit'].iloc[0] * 100 - 100)
    
    console.print(f"[blue]Total Trades:[/blue] {len(df)}")
    console.print(f"[blue]Total Profit:[/blue] {df['profit'].sum():.4f}")
    console.print(f"[blue]Win Rate:[/blue] {(df['profit'] > 0).sum() / len(df) * 100:.1f}%\n")
    
    # Create profit chart
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=df['close_date'],
        y=df['cumulative_profit'],
        mode='lines',
        name='Cumulative Profit',
        line=dict(color='green', width=2)
    ))
    
    # Add zero line
    fig.add_hline(y=0, line_dash='dash', line_color='white', opacity=0.5)
    
    # Add trade markers
    winning_trades = df[df['profit'] > 0]
    losing_trades = df[df['profit'] <= 0]
    
    fig.add_trace(go.Scatter(
        x=winning_trades['close_date'],
        y=winning_trades['cumulative_profit'],
        mode='markers',
        name='Winning',
        marker=dict(symbol='circle', size=8, color='green')
    ))
    
    fig.add_trace(go.Scatter(
        x=losing_trades['close_date'],
        y=losing_trades['cumulative_profit'],
        mode='markers',
        name='Losing',
        marker=dict(symbol='x', size=8, color='red')
    ))
    
    fig.update_layout(
        title='Cumulative Profit',
        xaxis_title='Time',
        yaxis_title='Cumulative Profit',
        template='plotly_dark',
        height=600,
        hovermode='x unified'
    )
    
    # Save to HTML
    output_path = output or 'plot_profit.html'
    fig.write_html(output_path)
    console.print(f"\n[green]✓ Plot saved to: {output_path}[/green]")
