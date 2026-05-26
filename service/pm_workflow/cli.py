"""CLI 入口 —— 脱离 n8n 也能从命令行触发全流程。

Phase 1 只占位，Phase 1.5 实现 scan-new-requirements 子命令。
"""

import click
from rich.console import Console

from pm_workflow import __version__

console = Console()


@click.group()
@click.version_option(__version__)
def cli():
    """PM 需求自动化系统 CLI。"""


@cli.command()
def info():
    """打印当前配置摘要（不暴露 secret）。"""
    from pm_workflow.config import get_settings

    s = get_settings()
    console.print("[bold]PM 需求自动化系统[/bold]")
    console.print(f"  version             : {__version__}")
    console.print(f"  llm_gateway_url     : {s.llm_gateway_url}")
    console.print(f"  llm_gateway_token   : {'已配置' if s.llm_gateway_token else '[red]缺[/red]'}")
    console.print(f"  notion_api_key      : {'已配置' if s.notion_api_key else '[red]缺[/red]'}")
    console.print(f"  notion_db_requirements: {s.notion_db_requirements or '[red]缺[/red]'}")
    console.print(f"  tavily_api_key      : {'已配置' if s.tavily_api_key else '[red]缺[/red]'}")
    console.print(f"  skill_library_dir   : {s.skill_library_dir}")


if __name__ == "__main__":
    cli()
