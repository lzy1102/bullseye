"""
Data Commands for Bullseye

Commands for downloading, listing, and converting market data.
"""
import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List

import click
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()
logger = logging.getLogger(__name__)

# Supported data formats
DATA_FORMATS = ['json', 'feather', 'parquet']

# Default timeframes to download
DEFAULT_TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d']


def timeframe_to_minutes(timeframe: str) -> int:
    """Convert timeframe string to minutes."""
    if timeframe.endswith('m'):
        return int(timeframe[:-1])
    elif timeframe.endswith('h'):
        return int(timeframe[:-1]) * 60
    elif timeframe.endswith('d'):
        return int(timeframe[:-1]) * 60 * 24
    elif timeframe.endswith('w'):
        return int(timeframe[:-1]) * 60 * 24 * 7
    elif timeframe == '1M':
        return 60 * 24 * 30
    return 0


def get_data_dir(exchange: str, user_data_dir: str = "user_data") -> Path:
    """Get data directory for exchange."""
    return Path(user_data_dir) / "data" / exchange


def _download_data_impl(exchange: Optional[str], pairs: Optional[str], timeframes: Optional[str],
                        days: int, timerange: Optional[str], data_format: str, prepend: bool,
                        erase: bool, config: Optional[str], dry_run: bool):
    """
    Internal implementation for downloading historical market data.
    Supports pagination to download large date ranges.
    """
    import time as time_module
    try:
        import ccxt
    except ImportError:
        console.print("[red]CCXT not installed. Install with: pip install ccxt[/red]")
        sys.exit(1)

    # Load configuration
    try:
        from ..configuration import Config
        config_obj = Config(config or "config.yaml")
        exchange = exchange or config_obj.get('exchange.name', 'binance')
        pairs_list = pairs.split(',') if pairs else config_obj.get('pairlist', ['BTC/USDT', 'ETH/USDT'])
        timeframes_list = timeframes.split(',') if timeframes else ['5m']
    except Exception:
        exchange = exchange or 'binance'
        pairs_list = pairs.split(',') if pairs else ['BTC/USDT', 'ETH/USDT']
        timeframes_list = timeframes.split(',') if timeframes else ['5m']

    # Parse timerange
    if timerange:
        try:
            start_str, end_str = timerange.split('-')
            start_date = datetime.strptime(start_str, '%Y%m%d')
            end_date = datetime.strptime(end_str, '%Y%m%d')
        except ValueError:
            console.print("[red]Invalid timerange format. Use: YYYYMMDD-YYYYMMDD[/red]")
            sys.exit(1)
    else:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

    console.print(f"[bold green]Downloading Market Data[/bold green]")
    console.print(f"[blue]Exchange:[/blue] {exchange}")
    console.print(f"[blue]Pairs:[/blue] {', '.join(pairs_list)}")
    console.print(f"[blue]Timeframes:[/blue] {', '.join(timeframes_list)}")
    console.print(f"[blue]Date Range:[/blue] {start_date.date()} to {end_date.date()}")
    console.print(f"[blue]Format:[/blue] {data_format}")

    if dry_run:
        console.print("\n[yellow]Dry run mode - no data will be downloaded[/yellow]")
        return

    # Create exchange instance
    try:
        exchange_class = getattr(ccxt, exchange.lower())
        exchange_instance = exchange_class({'enableRateLimit': True})
    except AttributeError:
        console.print(f"[red]Exchange '{exchange}' not supported by CCXT[/red]")
        sys.exit(1)

    # Create data directory
    data_dir = get_data_dir(exchange)
    data_dir.mkdir(parents=True, exist_ok=True)

    import pandas as pd
    from rich.progress import BarColumn, TimeElapsedColumn, TimeRemainingColumn

    total_pairs = len(pairs_list) * len(timeframes_list)
    pair_idx = 0

    for pair in pairs_list:
        for timeframe in timeframes_list:
            pair_idx += 1
            start_time = time_module.time()

            console.print(f"\n[cyan][{pair_idx}/{total_pairs}] {pair} {timeframe}[/cyan]")

            try:
                # Calculate expected candles
                timeframe_minutes = timeframe_to_minutes(timeframe)
                total_minutes = (end_date - start_date).total_seconds() / 60
                expected_candles = int(total_minutes / timeframe_minutes)

                # Download with pagination
                all_ohlcv = []
                current_since = int(start_date.timestamp() * 1000)
                end_timestamp = int(end_date.timestamp() * 1000)
                page = 0

                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                    TimeElapsedColumn(),
                    TimeRemainingColumn(),
                    console=console,
                    transient=True,
                ) as progress:
                    task_id = progress.add_task(
                        description=f"Downloading {expected_candles} candles...",
                        total=expected_candles,
                    )

                    while current_since < end_timestamp:
                        page += 1
                        try:
                            ohlcv = exchange_instance.fetch_ohlcv(pair, timeframe, since=current_since, limit=1000)
                        except Exception as e:
                            console.print(f"[yellow]  Warning: fetch error on page {page}: {e}[/yellow]")
                            break

                        if not ohlcv or len(ohlcv) == 0:
                            break

                        # Filter data within date range
                        for candle in ohlcv:
                            if candle[0] <= end_timestamp:
                                all_ohlcv.append(candle)

                        # Update progress
                        progress.update(task_id, completed=len(all_ohlcv))

                        # Get timestamp of last candle + 1 ms for next page
                        last_timestamp = ohlcv[-1][0]
                        if last_timestamp <= current_since:
                            break  # Prevent infinite loop
                        current_since = last_timestamp + 1

                        # Rate limiting
                        time_module.sleep(exchange_instance.rateLimit / 1000)

                # Convert to DataFrame
                if not all_ohlcv:
                    console.print(f"[yellow]  No data downloaded[/yellow]")
                    continue

                df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['date'] = pd.to_datetime(df['timestamp'], unit='ms')

                # Remove duplicates (same timestamp)
                df = df.drop_duplicates(subset=['timestamp'], keep='first')
                df = df.sort_values('timestamp')

                # Save data
                filename = f"{pair.replace('/', '_')}-{timeframe}.{data_format}"
                filepath = data_dir / filename

                if data_format == 'json':
                    df.to_json(filepath, orient='records', date_format='iso')
                elif data_format == 'feather':
                    df.to_feather(filepath)
                elif data_format == 'parquet':
                    df.to_parquet(filepath)

                elapsed = time_module.time() - start_time
                candles_per_sec = len(df) / elapsed if elapsed > 0 else 0
                console.print(f"[green]  ✓ Downloaded {len(df)} candles "
                             f"({df['date'].min()} to {df['date'].max()}) "
                             f"in {elapsed:.1f}s ({candles_per_sec:.0f} candles/s)[/green]")

            except Exception as e:
                console.print(f"[red]  ✗ Error: {e}[/red]")
                logger.exception("Download error")

    console.print(f"\n[green]✓ Data download complete![/green]")
    console.print(f"[blue]Data saved to:[/blue] {data_dir}")


@click.command(name='download-data')
@click.option('--exchange', '-e', type=str, help='Exchange name')
@click.option('--pairs', '-p', type=str, help='Trading pairs (comma-separated)')
@click.option('--timeframes', '-t', type=str, help='Timeframes (comma-separated)')
@click.option('--days', '-d', type=int, default=30, help='Number of days to download')
@click.option('--timerange', type=str, help='Time range (e.g., 20240101-20241231)')
@click.option('--data-format', type=click.Choice(DATA_FORMATS), default='json', help='Data format')
@click.option('--prepend', is_flag=True, help='Prepend to existing data')
@click.option('--erase', is_flag=True, help='Erase existing data')
@click.option('--config', '-c', type=str, help='Configuration file')
@click.option('--dry-run', is_flag=True, help='Show what would be downloaded without downloading')
def download_data(exchange: Optional[str], pairs: Optional[str], timeframes: Optional[str],
                  days: int, timerange: Optional[str], data_format: str, prepend: bool,
                  erase: bool, config: Optional[str], dry_run: bool):
    """
    Download historical market data

    Downloads OHLCV data from the exchange for backtesting and analysis.

    Examples:
        bullseye download-data --exchange binance --pairs BTC/USDT,ETH/USDT
        bullseye download-data --days 30 --timeframes 5m,1h
        bullseye download-data --timerange 20240101-20241231
        bullseye download-data --exchange binance --dry-run
    """
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


@click.command(name='list-data')
@click.option('--exchange', '-e', type=str, help='Exchange name')
@click.option('--data-format', type=str, help='Filter by data format')
@click.option('--print-json', is_flag=True, help='Output as JSON')
@click.option('--config', '-c', type=str, help='Configuration file')
def list_data(exchange: Optional[str], data_format: Optional[str], print_json: bool, config: Optional[str]):
    """
    List downloaded data
    
    Shows all downloaded historical data files.
    
    Examples:
        bullseye list-data
        bullseye list-data --exchange binance
        bullseye list-data --print-json
    """
    try:
        from ..configuration import Config
        config_obj = Config(config or "config.yaml")
        exchange = exchange or config_obj.get('exchange.name', 'binance')
    except Exception:
        exchange = exchange or 'binance'
    
    data_dir = get_data_dir(exchange)
    
    if not data_dir.exists():
        console.print(f"[yellow]No data directory found: {data_dir}[/yellow]")
        console.print("[yellow]Run 'bullseye download-data' first.[/yellow]")
        return
    
    # Find all data files
    data_files = []
    for fmt in DATA_FORMATS:
        for filepath in data_dir.glob(f"*.{fmt}"):
            # Parse filename: PAIR-TIMEFRAME.format
            filename = filepath.stem
            parts = filename.rsplit('-', 1)
            if len(parts) == 2:
                pair = parts[0].replace('_', '/')
                timeframe = parts[1]
                size = filepath.stat().st_size
                modified = datetime.fromtimestamp(filepath.stat().st_mtime)
                
                data_files.append({
                    'pair': pair,
                    'timeframe': timeframe,
                    'format': fmt,
                    'size': size,
                    'modified': modified,
                    'filepath': filepath
                })
    
    if not data_files:
        console.print(f"[yellow]No data files found in {data_dir}[/yellow]")
        return
    
    if print_json:
        import json
        output = [{
            'pair': f['pair'],
            'timeframe': f['timeframe'],
            'format': f['format'],
            'size_bytes': f['size'],
            'modified': f['modified'].isoformat()
        } for f in data_files]
        console.print(json.dumps(output, indent=2))
        return
    
    # Display as table
    console.print(f"[bold green]Downloaded Data ({exchange})[/bold green]\n")
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Pair", style="cyan")
    table.add_column("Timeframe", style="green")
    table.add_column("Format", style="blue")
    table.add_column("Size", style="yellow")
    table.add_column("Modified", style="white")
    
    # Sort by pair and timeframe
    data_files.sort(key=lambda x: (x['pair'], x['timeframe']))
    
    for f in data_files:
        size_str = f"{f['size'] / 1024:.1f} KB" if f['size'] < 1024*1024 else f"{f['size'] / (1024*1024):.1f} MB"
        table.add_row(
            f['pair'],
            f['timeframe'],
            f['format'],
            size_str,
            f['modified'].strftime('%Y-%m-%d %H:%M')
        )
    
    console.print(table)
    console.print(f"\n[dim]Total: {len(data_files)} files[/dim]")


@click.command(name='convert-data')
@click.option('--input-format', type=click.Choice(DATA_FORMATS), required=True, help='Input format')
@click.option('--output-format', type=click.Choice(DATA_FORMATS), required=True, help='Output format')
@click.option('--exchange', '-e', type=str, help='Exchange name')
@click.option('--pair', '-p', type=str, help='Trading pair')
@click.option('--timeframe', '-t', type=str, help='Timeframe')
@click.option('--config', '-c', type=str, help='Configuration file')
def convert_data(input_format: str, output_format: str, exchange: Optional[str],
                 pair: Optional[str], timeframe: Optional[str], config: Optional[str]):
    """
    Convert OHLCV data format
    
    Converts data files between JSON, Feather, and Parquet formats.
    
    Examples:
        bullseye convert-data --input-format json --output-format feather
        bullseye convert-data --input-format json --output-format parquet --pair BTC/USDT --timeframe 5m
    """
    if input_format == output_format:
        console.print("[yellow]Input and output formats are the same. Nothing to do.[/yellow]")
        return
    
    try:
        from ..configuration import Config
        config_obj = Config(config or "config.yaml")
        exchange = exchange or config_obj.get('exchange.name', 'binance')
    except Exception:
        exchange = exchange or 'binance'
    
    data_dir = get_data_dir(exchange)
    
    if not data_dir.exists():
        console.print(f"[red]Data directory not found: {data_dir}[/red]")
        sys.exit(1)
    
    # Find files to convert
    pattern = f"*-*.{input_format}"
    if pair and timeframe:
        pattern = f"{pair.replace('/', '_')}-{timeframe}.{input_format}"
    
    files_to_convert = list(data_dir.glob(pattern))
    
    if not files_to_convert:
        console.print(f"[yellow]No {input_format} files found to convert[/yellow]")
        return
    
    console.print(f"[bold green]Converting Data Format[/bold green]")
    console.print(f"[blue]Input:[/blue] {input_format}")
    console.print(f"[blue]Output:[/blue] {output_format}")
    console.print(f"[blue]Files:[/blue] {len(files_to_convert)}\n")
    
    import pandas as pd
    
    converted = 0
    errors = 0
    
    for filepath in files_to_convert:
        try:
            # Read input file
            if input_format == 'json':
                df = pd.read_json(filepath)
            elif input_format == 'feather':
                df = pd.read_feather(filepath)
            elif input_format == 'parquet':
                df = pd.read_parquet(filepath)
            
            # Write output file
            output_filepath = filepath.with_suffix(f'.{output_format}')
            
            if output_format == 'json':
                df.to_json(output_filepath, orient='records', date_format='iso')
            elif output_format == 'feather':
                df.to_feather(output_filepath)
            elif output_format == 'parquet':
                df.to_parquet(output_filepath)
            
            console.print(f"[green]✓ Converted: {filepath.name} -> {output_filepath.name}[/green]")
            converted += 1
            
        except Exception as e:
            console.print(f"[red]✗ Error converting {filepath.name}: {e}[/red]")
            errors += 1
    
    console.print(f"\n[green]✓ Conversion complete![/green]")
    console.print(f"[blue]Converted:[/blue] {converted}, [red]Errors:[/red] {errors}")


@click.command(name='convert-trade-data')
@click.option('--input-format', type=click.Choice(DATA_FORMATS), required=True, help='Input format')
@click.option('--output-format', type=click.Choice(DATA_FORMATS), required=True, help='Output format')
@click.option('--exchange', '-e', type=str, help='Exchange name')
@click.option('--pair', '-p', type=str, help='Trading pair')
def convert_trade_data(input_format: str, output_format: str, exchange: Optional[str], pair: Optional[str]):
    """
    Convert trade data format
    
    Converts tick/trade data between formats.
    
    Examples:
        bullseye convert-trade-data --input-format json --output-format parquet
    """
    # Similar to convert-data but for trade data
    console.print("[yellow]Trade data conversion - implementation pending[/yellow]")
    console.print("[dim]This command will convert tick/trade data files[/dim]")


@click.command(name='trades-to-ohlcv')
@click.option('--exchange', '-e', type=str, required=True, help='Exchange name')
@click.option('--pair', '-p', type=str, required=True, help='Trading pair')
@click.option('--timeframe', '-t', type=str, default='1m', help='Target timeframe')
@click.option('--data-format', type=click.Choice(DATA_FORMATS), default='json', help='Output format')
def trades_to_ohlcv(exchange: str, pair: str, timeframe: str, data_format: str):
    """
    Convert trade data to OHLCV
    
    Aggregates tick/trade data into OHLCV candles.
    
    Examples:
        bullseye trades-to-ohlcv --exchange binance --pair BTC/USDT --timeframe 5m
    """
    console.print(f"[bold green]Converting Trades to OHLCV[/bold green]")
    console.print(f"[blue]Exchange:[/blue] {exchange}")
    console.print(f"[blue]Pair:[/blue] {pair}")
    console.print(f"[blue]Timeframe:[/blue] {timeframe}")
    
    # Implementation would:
    # 1. Load trade data
    # 2. Resample to target timeframe
    # 3. Calculate OHLCV
    # 4. Save to file
    
    console.print("\n[yellow]Trade to OHLCV conversion - implementation pending[/yellow]")
    console.print("[dim]This command will aggregate trade data into OHLCV format[/dim]")
