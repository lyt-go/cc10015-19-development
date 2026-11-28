# -*- coding: utf-8 -*-
"""值班确认单领域服务：把排班实际签认人固化为一组当班责任人，供潜水下水登记核验。"""
from __future__ import annotations

from typing import Any

from app.services import duty_guard as guard
from app.services.base import BaseModuleService
from app.store import store


class DutyConfirmationService(BaseModuleService):
    MODULE = "duty_confirmation"
    ENTITY = "值班确认单"
    OPERATION_TERM = "岗位签认"
    LIST_FIELDS = [
        "确认单编号", "作业时段", "潜水员", "安全员", "值班领队", "关联排班", "备注说明",
    ]
    REQUIRED_FIELDS = ["作业时段"]
    STATUS_ORDER = [
        guard.CONFIRM_PENDING,
        guard.CONFIRM_PARTIAL,
        guard.CONFIRM_VERIFIED,
        guard.CONFIRM_REVOKED,
    ]
    ACTION_RULES = {
        "潜水员签认": guard.CONFIRM_PARTIAL,
        "安全员在途确认": guard.CONFIRM_PARTIAL,
        "领队交接": guard.CONFIRM_PARTIAL,
        "核销确认单": guard.CONFIRM_REVOKED,
    }
    NEGATIVE_ACTIONS = ["核销确认单"]

    ROLE_BY_ACTION = {
        "潜水员签认": guard.ROLE_DIVER,
        "安全员在途确认": guard.ROLE_SAFETY,
        "领队交接": guard.ROLE_LEADER,
    }

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [
            field for field in self.REQUIRED_FIELDS
            if not str(values.get(field) or "").strip()
        ]
        if missing:
            return None, missing
        try:
            entry = guard.create_confirmation(
                str(values["作业时段"]).strip(),
                operator=str(values.get("办理人") or "").strip() or None,
            )
        except guard.DutyRuleError as exc:
            if not exc.logged:
                guard.write_operation_log(
                    module=self.MODULE,
                    action="生成确认单",
                    result="拒绝",
                    message=str(exc),
                    shift=str(values["作业时段"]).strip(),
                    operator=str(values.get("办理人") or "").strip() or None,
                )
            return None, [str(exc)]
        return entry, []

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
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"

        if action == "核销确认单":
            idempotent_key = f"{self.MODULE}:{entry_id}:{action}"
            if store.is_idempotent(idempotent_key):
                return None, "动作「核销确认单」已执行，请勿重复操作"
            guard.revoke_confirmation(
                entry_id,
                "值班确认单人工核销",
                operator=operator or "值班领队",
            )
            store.mark_idempotent(idempotent_key)
            updated = store.find(self.MODULE, entry_id)
            return updated, f"{self.ENTITY}已核销"

        target_role = self.ROLE_BY_ACTION.get(action)
        if target_role is None:
            return None, f"动作「{action}」不属于{self.MODULE}可执行范围"

        if not operator or not str(operator).strip():
            return None, f"动作「{action}」必须由负责该作业时段的排班人本人办理，请填写办理人"
        if schedule_id is None:
            return None, f"动作「{action}」缺少排班标识，无法核对实际签认人"
        try:
            updated = guard.sign_slot(
                entry_id,
                target_role,
                str(operator).strip(),
                int(schedule_id),
                action_label=action,
            )
        except guard.DutyRuleError as exc:
            return None, str(exc)
        except (TypeError, ValueError):
            return None, "排班标识格式不正确，无法核对签认资格"

        idempotent_key = f"{self.MODULE}:{entry_id}:{action}:{schedule_id}"
        store.mark_idempotent(idempotent_key)
        return updated, f"{self.ENTITY}{action}已办理"

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        base["qualification"] = guard.qualification_summary()
        base["operation_logs"] = store.operation_logs(module=self.MODULE)
        return base
