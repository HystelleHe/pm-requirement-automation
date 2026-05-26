"""NotionClient 单测 —— mock httpx 调用验证 property 解构和 upsert 流程。"""

from unittest.mock import patch

from pm_workflow.config import Settings
from pm_workflow.notion import (
    NotionClient,
    Requirement,
    RequirementStatus,
    Skill,
    SkillStatus,
)


def _build_client() -> NotionClient:
    s = Settings(
        NOTION_API_KEY="test-key",
        NOTION_DB_REQUIREMENTS="db-req-id",
        NOTION_DB_SKILL_LIBRARY="db-skill-id",
    )
    return NotionClient(settings=s)


def test_query_requirements_parses_row():
    """需求表查询应将 Notion property 嵌套结构解析为 Requirement 模型。"""
    client = _build_client()
    fake_response = {
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
    with patch.object(client, "_query_db", return_value=fake_response) as mock_q:
        reqs = client.query_requirements(status=RequirementStatus.RESEARCHING)
    assert len(reqs) == 1
    r = reqs[0]
    assert isinstance(r, Requirement)
    assert r.page_id == "page-123"
    assert r.name == "PRD 自动化"
    assert r.competitors == ["Notion", "ClickUp"]
    assert r.status == RequirementStatus.RESEARCHING
    assert r.research_url == "https://example.com/r"
    assert r.req_id == "req-001"
    # 验证 filter 传给了 _query_db
    body = mock_q.call_args.args[1]
    assert body["filter"]["select"]["equals"] == "调研中"


def test_update_requirement_writes_only_passed_fields():
    """update 应只 patch 非 None 的字段。"""
    client = _build_client()
    with patch.object(client, "_patch", return_value={}) as mock_p:
        client.update_requirement("page-x", status=RequirementStatus.DONE, prd_url="https://prd")
    props = mock_p.call_args.kwargs["json"]["properties"]
    assert "状态" in props
    assert "PRD链接" in props
    assert "调研报告链接" not in props
    assert "失败原因" not in props


def test_update_requirement_noop_when_nothing_passed():
    """没有字段要更新时不应调 _patch。"""
    client = _build_client()
    with patch.object(client, "_patch") as mock_p:
        client.update_requirement("page-x")
    mock_p.assert_not_called()


def test_upsert_skill_creates_when_not_found():
    client = _build_client()
    skill = Skill(
        name="测试 Prompt",
        skill_key="test_skill",
        status=SkillStatus.ACTIVE,
        version="0.1.0",
        system_prompt="你是测试助手",
        pipeline=["竞品调研"],
    )
    with (
        patch.object(client, "_query_db", return_value={"results": []}),
        patch.object(client, "_post", return_value={"id": "new-page-id"}) as mock_post,
        patch.object(client, "_patch") as mock_patch,
    ):
        pid = client.upsert_skill(skill)
    assert pid == "new-page-id"
    mock_post.assert_called_once()
    mock_patch.assert_not_called()
    # 验证 _post 请求体含 parent.database_id
    post_kwargs = mock_post.call_args.kwargs
    assert post_kwargs["json"]["parent"]["database_id"] == "db-skill-id"


def test_upsert_skill_updates_when_found():
    client = _build_client()
    skill = Skill(name="x", skill_key="existing", version="1.0.0")
    with (
        patch.object(client, "_query_db", return_value={"results": [{"id": "existing-page-id"}]}),
        patch.object(client, "_patch", return_value={}) as mock_patch,
        patch.object(client, "_post") as mock_post,
    ):
        pid = client.upsert_skill(skill)
    assert pid == "existing-page-id"
    mock_patch.assert_called_once()
    mock_post.assert_not_called()


def test_skill_to_properties_only_writes_subset():
    """构造的 properties 应只含 10 字段子集。"""
    client = _build_client()
    skill = Skill(name="A", skill_key="a", version="1", pipeline=["竞品调研", "PRD"])
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
