"""NotionClient 单测 —— mock SDK 验证 property 解构和 upsert 流程。"""

from unittest.mock import MagicMock

from pm_workflow.config import Settings
from pm_workflow.notion import (
    NotionClient,
    Requirement,
    RequirementStatus,
    Skill,
    SkillStatus,
)


def _build_client_with_fake_sdk() -> tuple[NotionClient, MagicMock]:
    s = Settings(
        NOTION_API_KEY="test-key",
        NOTION_DB_REQUIREMENTS="db-req-id",
        NOTION_DB_SKILL_LIBRARY="db-skill-id",
    )
    client = NotionClient(settings=s)
    fake_sdk = MagicMock()
    client.sdk = fake_sdk
    return client, fake_sdk


def test_query_requirements_parses_row():
    """需求表查询应将 Notion property 嵌套结构解析为 Requirement 模型。"""
    client, sdk = _build_client_with_fake_sdk()
    sdk.databases.query.return_value = {
        "results": [
            {
                "id": "page-123",
                "properties": {
                    "需求名称": {"title": [{"plain_text": "PRD 自动化"}]},
                    "场景描述": {"rich_text": [{"plain_text": "面向 PM 团队的需求自动生成"}]},
                    "指定竞品": {"multi_select": [{"name": "Notion"}, {"name": "ClickUp"}]},
                    "自动发现关键词": {"rich_text": []},
                    "状态": {"select": {"name": "调研中"}},
                    "调研报告链接": {"url": "https://example.com/r"},
                    "需求拆解链接": {"url": None},
                    "PRD链接": {"url": None},
                    "失败原因": {"rich_text": []},
                    "req_id": {"rich_text": [{"plain_text": "req-001"}]},
                },
            }
        ]
    }

    reqs = client.query_requirements(status=RequirementStatus.RESEARCHING)
    assert len(reqs) == 1
    r = reqs[0]
    assert isinstance(r, Requirement)
    assert r.page_id == "page-123"
    assert r.name == "PRD 自动化"
    assert r.scenario == "面向 PM 团队的需求自动生成"
    assert r.competitors == ["Notion", "ClickUp"]
    assert r.status == RequirementStatus.RESEARCHING
    assert r.research_url == "https://example.com/r"
    assert r.req_id == "req-001"
    # 验证 filter 传给了 SDK
    call_kwargs = sdk.databases.query.call_args.kwargs
    assert call_kwargs["filter"]["select"]["equals"] == "调研中"


def test_update_requirement_writes_only_passed_fields():
    """update 应只传入非 None 的字段，未传的字段不进 properties。"""
    client, sdk = _build_client_with_fake_sdk()
    client.update_requirement("page-x", status=RequirementStatus.DONE, prd_url="https://prd")
    props = sdk.pages.update.call_args.kwargs["properties"]
    assert "状态" in props
    assert "PRD链接" in props
    # 没传的字段不应该出现
    assert "调研报告链接" not in props
    assert "失败原因" not in props


def test_upsert_skill_creates_when_not_found():
    """upsert: skill_key 未找到时调 pages.create。"""
    client, sdk = _build_client_with_fake_sdk()
    sdk.databases.query.return_value = {"results": []}
    sdk.pages.create.return_value = {"id": "new-page-id"}
    skill = Skill(
        name="测试 Prompt",
        skill_key="test_skill",
        status=SkillStatus.ACTIVE,
        version="0.1.0",
        system_prompt="你是测试助手",
        pipeline=["竞品调研"],
    )
    pid = client.upsert_skill(skill)
    assert pid == "new-page-id"
    sdk.pages.create.assert_called_once()
    sdk.pages.update.assert_not_called()


def test_upsert_skill_updates_when_found():
    """upsert: skill_key 已存在时调 pages.update。"""
    client, sdk = _build_client_with_fake_sdk()
    sdk.databases.query.return_value = {"results": [{"id": "existing-page-id"}]}
    skill = Skill(name="x", skill_key="existing", version="1.0.0")
    pid = client.upsert_skill(skill)
    assert pid == "existing-page-id"
    sdk.pages.update.assert_called_once_with(
        page_id="existing-page-id",
        properties=client._skill_to_properties(skill),
    )
    sdk.pages.create.assert_not_called()


def test_skill_to_properties_only_writes_subset():
    """构造的 properties 应只含 10 字段子集，不含其它列。"""
    client, _ = _build_client_with_fake_sdk()
    skill = Skill(
        name="A", skill_key="a", version="1", pipeline=["竞品调研", "PRD"]
    )
    props = client._skill_to_properties(skill)
    expected_keys = {
        "Name",
        "Skill Key",
        "Status",
        "Version",
        "Description",
        "System Prompt",
        "User Prompt Template",
        "Input Variables",
        "Output Schema",
        "Model Preference",
        "适用管线",
    }
    assert set(props.keys()) == expected_keys
    assert props["适用管线"]["multi_select"] == [{"name": "竞品调研"}, {"name": "PRD"}]
