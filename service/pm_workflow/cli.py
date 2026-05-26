"""CLI 入口 —— 脱离 n8n 也能从命令行触发全流程。

常用：
- `pm-workflow info` 看配置摘要
- `pm-workflow scan-new-requirements` 列出待处理需求（Phase 2-4 用来人工触发）
- `pm-workflow skills-sync` 手动同步本地 skill-library/ 到 Notion
- `pm-workflow skills-list --pipeline 竞品调研` 看 Skill Library 内容
"""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

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
    console.print(f"  project_root        : {s.skill_library_dir.parent}")
    console.print(f"  llm_gateway_url     : {s.llm_gateway_url}")
    console.print(f"  llm_gateway_token   : {'已配置' if s.llm_gateway_token else '[red]缺[/red]'}")
    console.print(f"  notion_api_key      : {'已配置' if s.notion_api_key else '[red]缺[/red]'}")
    console.print(f"  notion_db_requirements : {s.notion_db_requirements or '[red]缺[/red]'}")
    console.print(f"  notion_db_skill_library: {s.notion_db_skill_library or '[red]缺[/red]'}")
    console.print(f"  tavily_api_key      : {'已配置' if s.tavily_api_key else '[red]缺[/red]'}")
    console.print(
        f"  langfuse trace      : {'启用' if (s.langfuse_public_key and s.langfuse_secret_key) else '未启用'}"
    )


@cli.command(name="scan-new-requirements")
@click.option("--status", default="待处理", help="过滤的状态名（与 Notion select option 一致）")
@click.option("--all", "show_all", is_flag=True, help="忽略状态过滤，显示全部需求")
@click.option("--limit", type=int, default=10, help="最多展示几条")
def scan_new_requirements(status: str, show_all: bool, limit: int):
    """扫描 Notion 需求表，打印待处理需求清单（ROADMAP Phase 1 的验收点）。"""
    from pm_workflow.notion import NotionClient

    with NotionClient() as notion:
        reqs = notion.query_requirements(status=None if show_all else status)

    label = "全部状态" if show_all else f"状态={status}"
    if not reqs:
        console.print(f"[yellow]需求表无匹配行（{label}）[/yellow]")
        return

    console.print(f"[bold green]扫描到 {len(reqs)} 条需求（{label}），展示前 {min(limit, len(reqs))}：[/bold green]\n")
    for r in reqs[:limit]:
        console.print(f"[bold cyan]● {r.name}[/bold cyan]")
        console.print(f"  page_id   : {r.page_id}")
        console.print(f"  status    : [magenta]{r.status.value}[/magenta]")
        console.print(f"  req_id    : {r.req_id or '[dim](待生成)[/dim]'}")
        scenario = r.scenario.strip() or "[dim](空)[/dim]"
        if len(scenario) > 200:
            scenario = scenario[:200] + "..."
        console.print(f"  场景      : {scenario}")
        console.print(f"  指定竞品  : {', '.join(r.competitors) or '[dim](无)[/dim]'}")
        if r.research_url:
            console.print(f"  调研报告  : {r.research_url}")
        if r.prd_url:
            console.print(f"  PRD       : {r.prd_url}")
        console.print()


@cli.command(name="skills-sync")
def skills_sync():
    """手动触发 skill-library/ → Notion 同步。"""
    from pm_workflow.agents.skill_sync import SkillSyncer

    results = SkillSyncer().sync()
    if not results:
        console.print("[yellow]skill-library/ 下没有可同步的 md 文件[/yellow]")
        return
    table = Table(title="Skill 同步结果")
    table.add_column("skill_key", style="cyan")
    table.add_column("状态")
    for key, status in results.items():
        color = {"created": "green", "updated": "yellow", "unchanged": "dim"}.get(status, "red")
        table.add_row(key, f"[{color}]{status}[/{color}]")
    console.print(table)


@cli.command(name="skills-list")
@click.option("--pipeline", default=None, help="按适用管线过滤，如 竞品调研/PRD/Figma")
@click.option("--all", "show_all", is_flag=True, help="包含非 Active 状态")
def skills_list(pipeline: str | None, show_all: bool):
    """列出 Notion Skill Library 当前可用的 skill。"""
    from pm_workflow.notion import NotionClient, SkillStatus

    with NotionClient() as notion:
        skills = notion.list_skills()
    if not show_all:
        skills = [s for s in skills if s.status == SkillStatus.ACTIVE]
    if pipeline:
        skills = [s for s in skills if pipeline in s.pipeline]
    if not skills:
        console.print("[yellow]无匹配的 skill[/yellow]")
        return
    table = Table(title=f"Skills（{len(skills)} 条）")
    table.add_column("skill_key", style="cyan")
    table.add_column("name")
    table.add_column("model", style="magenta")
    table.add_column("pipeline")
    table.add_column("status")
    for s in skills:
        table.add_row(
            s.skill_key,
            s.name,
            s.model_preference,
            ", ".join(s.pipeline),
            s.status.value,
        )
    console.print(table)


if __name__ == "__main__":
    cli()
