"""Logging configuration for ZTWIM Test Framework."""

import logging
import sys
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler

from .config import get_settings

# Global console for rich output
console = Console()


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Get a configured logger instance.
    
    Args:
        name: Logger name (default: 'ztwim')
    
    Returns:
        Configured logger instance
    """
    settings = get_settings()
    logger_name = name or "ztwim"
    
    logger = logging.getLogger(logger_name)
    
    # Only configure if not already configured
    if not logger.handlers:
        logger.setLevel(getattr(logging, settings.logging.level.upper()))
        
        # Rich handler for console output
        rich_handler = RichHandler(
            console=console,
            show_time=True,
            show_path=False,
            rich_tracebacks=True,
        )
        rich_handler.setLevel(logging.DEBUG)
        
        # Simple formatter for rich handler
        formatter = logging.Formatter("%(message)s")
        rich_handler.setFormatter(formatter)
        
        logger.addHandler(rich_handler)
        
        # Allow propagation so pytest's log_file handler captures logs
        logger.propagate = True
    
    return logger


def log_test_start(test_name: str) -> None:
    """Log test start with visual separator."""
    console.print(f"\n[bold blue]{'='*60}[/bold blue]")
    console.print(f"[bold green]▶ Starting:[/bold green] {test_name}")
    console.print(f"[bold blue]{'='*60}[/bold blue]\n")


def log_test_end(test_name: str, passed: bool) -> None:
    """Log test end with result."""
    status = "[bold green]✓ PASSED[/bold green]" if passed else "[bold red]✗ FAILED[/bold red]"
    console.print(f"\n[bold blue]{'─'*60}[/bold blue]")
    console.print(f"{status}: {test_name}")
    console.print(f"[bold blue]{'─'*60}[/bold blue]\n")


def log_step(step: str) -> None:
    """Log a test step."""
    console.print(f"  [cyan]→[/cyan] {step}")


def log_info(message: str) -> None:
    """Log info message."""
    console.print(f"  [blue]ℹ[/blue] {message}")


def log_success(message: str) -> None:
    """Log success message."""
    console.print(f"  [green]✓[/green] {message}")


def log_warning(message: str) -> None:
    """Log warning message."""
    console.print(f"  [yellow]⚠[/yellow] {message}")


def log_error(message: str) -> None:
    """Log error message."""
    console.print(f"  [red]✗[/red] {message}")
