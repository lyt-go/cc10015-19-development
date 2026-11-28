"""航次计划领域服务：提供航次计划的全生命周期管理，作为其他模块的前置依赖。
支持事务快照回滚。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class CruisePlanService(BaseModuleService):
    MODULE = "cruise_plan"
    ENTITY = "航次计划书"
    OPERATION_TERM = "提交审阅"
    LIST_FIELDS = ["航次编号", "调查海域", "起止日期", "观测目标", "搭载设备", "首席科学家", "计划状态", "备注说明"]
    REQUIRED_FIELDS = ["航次编号", "调查海域", "起止日期"]
    STATUS_ORDER = ["编制中", "已提交", "已批准", "已变更"]
    ACTION_RULES = {"提交审阅": "已提交", "批准计划": "已批准", "变更计划": "已变更"}
    NEGATIVE_ACTIONS = []

    def is_approved(self) -> bool:
        """检查是否存在已批准的航次计划——站位布设等模块的前置条件。"""
        rows = store.rows(self.MODULE)
        return any(row.get("status") == "已批准" for row in rows)

    def get_approved_plan(self) -> dict[str, Any] | None:
        """获取当前已批准的航次计划。"""
        rows = store.rows(self.MODULE)
        for row in rows:
            if row.get("status") == "已批准":
                return dict(row)
        return None

    def run_action(
        self,
        entry_id: int,
        action: str,
        *,
        operator: str | None = None,
        role: str | None = None,
        schedule_id: int | None = None,
        **_: Any,
    ) -> tuple[dict[str, Any] | None, str]:
        """执行动作，增加变更计划时的业务规则校验和回滚支持。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"

        target = self.ACTION_RULES.get(action)
        if target is None:
            return None, f"动作「{action}」不属于{self.MODULE}可执行范围"

        # 幂等检查
        idempotent_key = f"{self.MODULE}:{entry_id}:{action}"
        if store.is_idempotent(idempotent_key):
            return None, f"动作「{action}」已执行，请勿重复操作"

        # 保存操作前快照
        tx_id = f"{self.MODULE}:{entry_id}:{action}:tx"
        store.save_snapshot(tx_id, self.MODULE, entry_id)

        # 执行状态变更
        if action == "变更计划" and entry.get("status") != "已批准":
            return None, "只能变更已批准的航次计划"
        if action == "批准计划" and entry.get("status") != "已提交":
            return None, "只能批准已提交的航次计划"

        old_status = entry.get("status")
        entry["status"] = target
        entry["pending"] = target not in ("已批准", "已变更")
        entry["abnormal"] = action in self.NEGATIVE_ACTIONS

        if action == "变更计划":
            entry["pending"] = True

        store.mark_idempotent(idempotent_key)

        # 变更计划时通知受影响的后置模块
        if action == "变更计划":
            self._notify_plan_changed(entry)

        return entry, f"{self.ENTITY}已{action}"

    def _notify_plan_changed(self, entry: dict[str, Any]) -> None:
        """航次计划变更后通知站位布设等模块标记需重新评估。"""
        station_rows = store.rows("station_deploy")
        for row in station_rows:
            if row.get("status") in ("已布设", "已作业"):
                row["plan_changed"] = True
                row["plan_change_msg"] = "航次计划已变更，请重新评估站位"