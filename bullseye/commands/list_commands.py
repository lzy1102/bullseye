"""
List Commands for Bullseye

Commands for listing exchanges, markets, pairs, and other information.
"""
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

console = Console()

# Hyperopt loss functions (same as Freqtrade)
HYPEROPT_LOSS_FUNCTIONS = {
    'ShortTradeDurHyperOptLoss': 'Optimize for short trade duration and profit',
    'OnlyProfitHyperOptLoss': 'Optimize for total profit only',
    'SharpeHyperOptLoss': 'Optimize for Sharpe ratio (hourly)',
    'SharpeHyperOptLossDaily': 'Optimize for Sharpe ratio (daily)',
    'SortinoHyperOptLoss': 'Optimize for Sortino ratio (hourly)',
    'SortinoHyperOptLossDaily': 'Optimize for Sortino ratio (daily)',
    'CalmarHyperOptLoss': 'Optimize for Calmar ratio',
}

# Supported timeframes
TIMEFRAMES = [
    ("1m", "1 minute", "Short-term scalping"),
    ("3m", "3 minutes", "Scalping"),
    ("5m", "5 minutes", "Short-term trading"),
    ("15m", "15 minutes", "Intraday trading"),
    ("30m", "30 minutes", "Intraday trading"),
    ("1h", "1 hour", "Swing trading"),
    ("2h", "2 hours", "Swing trading"),
    ("4h", "4 hours", "Medium-term trading"),
    ("6h", "6 hours", "Medium-term trading"),
    ("8h", "8 hours", "Long-term trading"),
    ("12h", "12 hours", "Long-term trading"),
    ("1d", "1 day", "Position trading"),
    ("3d", "3 days", "Position trading"),
    ("1w", "1 week", "Long-term investing"),
    ("1M", "1 month", "Very long-term"),
]

# Crypto exchanges supported by CCXT
CRYPTO_EXCHANGES = [
    ("binance", "Binance", "Spot & Futures", "✓"),
    ("binanceus", "Binance US", "Spot", "✓"),
    ("okx", "OKX", "Spot & Futures", "✓"),
    ("bybit", "Bybit", "Spot & Futures", "✓"),
    ("gate", "Gate.io", "Spot & Futures", "✓"),
    ("kucoin", "KuCoin", "Spot & Futures", "✓"),
    ("bitget", "Bitget", "Spot & Futures", "✓"),
    ("kraken", "Kraken", "Spot & Futures", "✓"),
    ("coinbase", "Coinbase", "Spot", "✓"),
    ("bitfinex", "Bitfinex", "Spot & Margin", "✓"),
    ("huobi", "HTX (Huobi)", "Spot & Futures", "✓"),
    ("bingx", "BingX", "Spot & Futures", "✓"),
    ("bitmart", "BitMart", "Spot", "✓"),
    ("bitvavo", "Bitvavo", "Spot", "Community"),
    ("luno", "Luno", "Spot", "Community"),
]

# Stock gateways (China)
STOCK_GATEWAYS = [
    ("xtp", "XTP (中泰证券)", "L1/L2行情", "✓"),
    ("tora", "TORA (华鑫奇点)", "L1/L2行情", "✓"),
    ("ost", "OST (东证)", "L1行情", "✓"),
    ("emt", "EMT (东方财富)", "L1行情", "✓"),
]

# Futures gateways (China)
FUTURES_GATEWAYS = [
    ("ctp", "CTP (SimNow/实盘)", "上期所/大商所/郑商所/中金所", "✓"),
    ("minictp", "MiniCTP", "轻量级CTP", "✓"),
    ("femas", "FEMAS (飞马)", "中金所", "✓"),
    ("uft", "UFT (恒生)", "多交易所", "✓"),
]

# International gateways
INTL_GATEWAYS = [
    ("ib", "Interactive Brokers", "全球股票/期货/期权", "✓"),
    ("tap", "TAP (易盛)", "外盘期货", "✓"),
    ("da", "DA (直达)", "外盘期货", "✓"),
]


@click.command(name='list-exchanges')
@click.option('--market-type', type=click.Choice(['crypto', 'stock', 'future', 'all']), 
              default='all', help='Filter by market type')
def list_exchanges(market_type: str):
    """
    List supported exchanges and gateways
    
    Shows all supported exchanges for different market types.
    
    Examples:
        bullseye list-exchanges
        bullseye list-exchanges --market-type crypto
        bullseye list-exchanges --market-type stock
    """
    console.print("[bold green]Supported Exchanges and Gateways[/bold green]\n")
    
    if market_type in ('all', 'crypto'):
        console.print("[bold cyan]Cryptocurrency Exchanges (via CCXT):[/bold cyan]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Exchange ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Markets", style="blue")
        table.add_column("Status", style="yellow")
        
        for ex_id, name, markets, status in CRYPTO_EXCHANGES:
            table.add_row(ex_id, name, markets, status)
        console.print(table)
        console.print()
    
    if market_type in ('all', 'stock'):
        console.print("[bold cyan]Stock Gateways (China A-shares):[/bold cyan]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Gateway", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Features", style="blue")
        table.add_column("Status", style="yellow")
        
        for gw_id, name, features, status in STOCK_GATEWAYS:
            table.add_row(gw_id, name, features, status)
        console.print(table)
        console.print()
    
    if market_type in ('all', 'future'):
        console.print("[bold cyan]Futures Gateways (China):[/bold cyan]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Gateway", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Exchanges", style="blue")
        table.add_column("Status", style="yellow")
        
        for gw_id, name, exchanges, status in FUTURES_GATEWAYS:
            table.add_row(gw_id, name, exchanges, status)
        console.print(table)
        console.print()
    
    if market_type in ('all',):
        console.print("[bold cyan]International Gateways:[/bold cyan]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Gateway", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Markets", style="blue")
        table.add_column("Status", style="yellow")
        
        for gw_id, name, markets, status in INTL_GATEWAYS:
            table.add_row(gw_id, name, markets, status)
        console.print(table)


@click.command(name='list-markets')
@click.option('--exchange', '-e', type=str, help='Exchange name')
@click.option('--quote', type=str, help='Filter by quote currency (e.g., USDT)')
@click.option('--active-only', is_flag=True, help='Show only active markets')
@click.option('--print-json', is_flag=True, help='Output as JSON')
@click.option('--config', '-c', type=str, help='Configuration file')
def list_markets(exchange: Optional[str], quote: Optional[str], 
                 active_only: bool, print_json: bool, config: Optional[str]):
    """
    List markets on exchange
    
    Shows all available markets/trading pairs on the specified exchange.
    
    Examples:
        bullseye list-markets --exchange binance
        bullseye list-markets --exchange binance --quote USDT
        bullseye list-markets --active-only
    """
    try:
        import ccxt
        
        # Get exchange name from config or parameter
        if not exchange:
            try:
                from ..configuration import Config
                config_obj = Config(config or "config.yaml")
                exchange = config_obj.get('exchange.name', 'binance')
            except:
                exchange = 'binance'
        
        console.print(f"[green]Fetching markets from {exchange}...[/green]\n")
        
        # Create exchange instance
        exchange_class = getattr(ccxt, exchange.lower())
        exchange_instance = exchange_class({'enableRateLimit': True})
        
        # Load markets
        markets = exchange_instance.load_markets()
        
        # Filter markets
        filtered_markets = []
        for symbol, market in markets.items():
            if active_only and not market.get('active', True):
                continue
            if quote and market.get('quote') != quote.upper():
                continue
            filtered_markets.append((symbol, market))
        
        if print_json:
            import json
            output = {symbol: {
                'base': m['base'],
                'quote': m['quote'],
                'active': m.get('active', True),
                'type': m.get('type', 'spot'),
            } for symbol, m in filtered_markets}
            console.print(json.dumps(output, indent=2))
            return
        
        # Display as table
        console.print(f"[bold green]Markets on {exchange}[/bold green]")
        console.print(f"[dim]Total: {len(filtered_markets)} markets[/dim]\n")
        
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Symbol", style="cyan")
        table.add_column("Base", style="green")
        table.add_column("Quote", style="blue")
        table.add_column("Type", style="yellow")
        table.add_column("Active", style="white")
        
        # Show first 100 markets
        for symbol, market in filtered_markets[:100]:
            table.add_row(
                symbol,
                market.get('base', 'N/A'),
                market.get('quote', 'N/A'),
                market.get('type', 'spot'),
                "✓" if market.get('active', True) else "✗"
            )
        
        console.print(table)
        
        if len(filtered_markets) > 100:
            console.print(f"\n[yellow]... and {len(filtered_markets) - 100} more markets[/yellow]")
        
    except ImportError:
        console.print("[red]CCXT not installed. Install with: pip install ccxt[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error fetching markets: {e}[/red]")
        sys.exit(1)


@click.command(name='list-pairs')
@click.option('--exchange', '-e', type=str, help='Exchange name')
@click.option('--quote', type=str, help='Filter by quote currency')
@click.option('--print-json', is_flag=True, help='Output as JSON')
@click.option('--config', '-c', type=str, help='Configuration file')
def list_pairs(exchange: Optional[str], quote: Optional[str], 
               print_json: bool, config: Optional[str]):
    """
    List trading pairs
    
    Shows available trading pairs, similar to list-markets but
    formatted for pairlist configuration.
    
    Examples:
        bullseye list-pairs --exchange binance --quote USDT
        bullseye list-pairs --print-json
    """
    try:
        import ccxt
        
        # Get exchange name
        if not exchange:
            try:
                from ..configuration import Config
                config_obj = Config(config or "config.yaml")
                exchange = config_obj.get('exchange.name', 'binance')
            except:
                exchange = 'binance'
        
        console.print(f"[green]Fetching pairs from {exchange}...[/green]\n")
        
        # Create exchange instance
        exchange_class = getattr(ccxt, exchange.lower())
        exchange_instance = exchange_class({'enableRateLimit': True})
        
        # Load markets
        markets = exchange_instance.load_markets()
        
        # Filter for spot markets only
        pairs = []
        for symbol, market in markets.items():
            if market.get('type') != 'spot':
                continue
            if quote and market.get('quote') != quote.upper():
                continue
            if not market.get('active', True):
                continue
            pairs.append(symbol)
        
        # Sort pairs
        pairs.sort()
        
        if print_json:
            import json
            console.print(json.dumps(pairs, indent=2))
            return
        
        # Display
        console.print(f"[bold green]Trading Pairs on {exchange}[/bold green]")
        console.print(f"[dim]Total: {len(pairs)} pairs[/dim]\n")
        
        # Format for pairlist config
        console.print("[yellow]Pairs for configuration file:[/yellow]")
        console.print("```yaml")
        console.print("pairlist:")
        console.print("  - method: StaticPairList")
        console.print("    config:")
        console.print("      pairs:")
        for pair in pairs[:50]:  # Show first 50
            console.print(f"        - {pair}")
        console.print("```")
        
        if len(pairs) > 50:
            console.print(f"\n[yellow]... and {len(pairs) - 50} more pairs[/yellow]")
        
    except ImportError:
        console.print("[red]CCXT not installed. Install with: pip install ccxt[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error fetching pairs: {e}[/red]")
        sys.exit(1)


@click.command(name='list-hyperoptloss')
@click.option('--print-json', is_flag=True, help='Output as JSON')
def list_hyperoptloss(print_json: bool):
    """
    List available hyperopt loss functions
    
    Shows all built-in loss functions for hyperparameter optimization.
    
    Examples:
        bullseye list-hyperoptloss
        bullseye list-hyperoptloss --print-json
    """
    if print_json:
        import json
        console.print(json.dumps(HYPEROPT_LOSS_FUNCTIONS, indent=2))
        return
    
    console.print("[bold green]Available Hyperopt Loss Functions[/bold green]\n")
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Loss Function", style="cyan")
    table.add_column("Description", style="green")
    
    for name, description in HYPEROPT_LOSS_FUNCTIONS.items():
        table.add_row(name, description)
    
    console.print(table)
    
    console.print("\n[yellow]Usage in configuration:[/yellow]")
    console.print("```yaml")
    console.print("hyperopt:")
    console.print("  loss_function: SharpeHyperOptLoss")
    console.print("```")


@click.command(name='list-timeframes')
def list_timeframes():
    """
    List supported timeframes
    
    Shows all supported timeframe codes and their descriptions.
    
    Examples:
        bullseye list-timeframes
    """
    console.print("[bold green]Supported Timeframes[/bold green]\n")
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Code", style="cyan")
    table.add_column("Description", style="green")
    table.add_column("Use Case", style="blue")
    
    for code, desc, use_case in TIMEFRAMES:
        table.add_row(code, desc, use_case)
    
    console.print(table)
    
    console.print("\n[yellow]Usage in strategy:[/yellow]")
    console.print("```python")
    console.print("class MyStrategy(IStrategy):")
    console.print("    timeframe = '5m'")
    console.print("```")
