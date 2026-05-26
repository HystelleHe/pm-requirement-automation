"""通知子包 —— 飞书 webhook + 本地 stdout 兜底。

import 入口：
    from pm_workflow.notifier import Notifier, StageEvent
"""

from pm_workflow.notifier.feishu import Notifier, StageEvent

__all__ = ["Notifier", "StageEvent"]
