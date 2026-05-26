"""验证配置加载正确。"""

from pm_workflow.config import Settings, get_settings


def test_settings_singleton():
    """get_settings 应该返回同一个实例（缓存）。"""
    assert get_settings() is get_settings()


def test_default_models():
    """模型路由默认值应符合 ROADMAP 决策。"""
    s = Settings()
    assert s.llm_model_breakdown == "moonshotai/Kimi-K2-Thinking"
    assert s.llm_model_prd_writer == "moonshotai/Kimi-K2-Thinking"
    assert s.llm_model_prd_critic == "glm-5-turbo"  # 跨家审校
    assert s.llm_model_eval_judge == "glm-5-turbo"


def test_paths_resolved():
    """计算属性应指向项目根目录的实际子目录。"""
    s = Settings()
    assert s.skill_library_dir.name == "skill-library"
    assert s.outputs_dir.name == "outputs"
