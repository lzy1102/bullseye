"""
Webserver Commands for Bullseye

Commands for starting the REST API server.
"""
import sys
from typing import Optional

import click
from rich.console import Console

console = Console()


@click.command(name='webserver')
@click.option('--host', '-h', type=str, default='127.0.0.1', help='Host to bind to')
@click.option('--port', '-p', type=int, default=8080, help='Port to bind to')
@click.option('--config', '-c', type=str, help='Configuration file')
@click.option('--reload', is_flag=True, help='Enable auto-reload')
def webserver(host: str, port: int, config: Optional[str], reload: bool):
    """
    Start the REST API server
    
    Starts the FastAPI server for controlling the trading bot.
    
    Examples:
        bullseye webserver
        bullseye webserver --host 0.0.0.0 --port 8000
        bullseye webserver --config config.yaml
    """
    console.print("[bold green]Starting Bullseye API Server[/bold green]")
    console.print(f"[blue]Host:[/blue] {host}")
    console.print(f"[blue]Port:[/blue] {port}")
    console.print(f"[blue]Config:[/blue] {config or 'Default'}")
    console.print(f"[blue]Auto-reload:[/blue] {reload}\n")

    try:
        from ..rpc.api_server import create_app, start_api_server

        # Load config
        config_dict = None
        if config:
            try:
                import yaml
                with open(config, 'r') as f:
                    config_dict = yaml.safe_load(f)
            except Exception as e:
                console.print(f"[yellow]Warning: Could not load config: {e}[/yellow]")

        # Create app
        app = create_app(config_dict)

        # Start server
        start_api_server(app, host=host, port=port)

    except ImportError as e:
        console.print(f"[red]Error: {e}[/red]")
        console.print("[yellow]Please install required dependencies:[/yellow]")
        console.print("  pip install fastapi uvicorn websockets python-jose")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error starting server: {e}[/red]")
        sys.exit(1)
