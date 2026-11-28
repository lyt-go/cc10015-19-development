# -*- coding: utf-8 -*-
"""潜水作业领域服务。

下水登记必须关联一张有效值班确认单上两名实际有资格的队员（潜水员、安全员）；
潜水中止后核销受影响的签认资格，已中止的作业不能凭旧值班确认再次登记下水。
"""
from __future__ import annotations

from typing import Any

from app.services import duty_guard as guard
from app.services.base import BaseModuleService
from app.store import store


class DivingOpsService(BaseModuleService):
    MODULE = "diving_ops"
    ENTITY = "潜水记录"
    OPERATION_TERM = "确认下水"
    LIST_FIELDS = [
        "潜水地点", "潜水深度", "潜水时长", "作业内容", "潜水员", "安全员",
        "作业时段", "值班确认单", "下水时间", "备注说明",
    ]
    REQUIRED_FIELDS = ["潜水地点", "潜水深度", "潜水时长", "作业时段", "潜水员", "安全员"]
    STATUS_ORDER = ["待准备", "已下水", "已完成", "已中止"]
    ACTION_RULES = {"确认下水": "已下水", "完成作业": "已完成", "中止潜水": "已中止"}
    NEGATIVE_ACTIONS = ["中止潜水"]

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [
            field for field in self.REQUIRED_FIELDS
            if not str(values.get(field) or "").strip()
        ]
        if missing:
            return None, missing

        shift = str(values["作业时段"]).strip()
        diver_name = str(values["潜水员"]).strip()
        safety_name = str(values["安全员"]).strip()
        try:
            confirmation = guard.validate_launch_qualification(
                shift, diver_name, safety_name,
                operator=str(values.get("办理人") or "").strip() or None,
            )
        except guard.DutyRuleError as exc:
            return None, [str(exc)]

        rows = store.rows(self.MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in self.LIST_FIELDS})
        entry["status"] = self.STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["作业时段"] = shift
        entry["值班确认单"] = confirmation["id"]
        entry["确认单编号"] = confirmation.get("确认单编号")
        entry["diver_schedule_id"] = next(
            (s["schedule_id"] for s in confirmation["slots"]
             if s.get("role") == guard.ROLE_DIVER and not s.get("revoked")),
            None,
        )
        entry["safety_schedule_id"] = next(
            (s["schedule_id"] for s in confirmation["slots"]
             if s.get("role") == guard.ROLE_SAFETY and not s.get("revoked")),
            None,
        )
        rows.append(entry)
        return entry, []

    def run_action(
        self,
        entry_id: int,
        action: str,
        *,
        operator: str | None = None,
        **_: Any,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"

        target = self.ACTION_RULES.get(action)
        if target is None:
            return None, f"动作「{action}」不属于{self.MODULE}可执行范围"

        # 中止潜水前只能是已下水或已完成状态
        if action == "中止潜水" and entry.get("status") not in ("已下水", "已完成"):
            return None, "只能中止已下水或已完成的潜水作业"

        # 确认下水：先核验值班资格（中止核销后旧确认单必须被拦住），再做幂等判断
        if action == "确认下水":
            blocked = self._launch_blocker(entry, operator)
            if blocked is not None:
                return None, blocked

        # 幂等检查
        idempotent_key = f"{self.MODULE}:{entry_id}:{action}"
        if store.is_idempotent(idempotent_key):
            return None, f"动作「{action}」已执行，请勿重复操作"

        entry["status"] = target
        entry["pending"] = target in ("待准备", "已下水")
        entry["abnormal"] = action in self.NEGATIVE_ACTIONS

        store.mark_idempotent(idempotent_key)

        if action == "确认下水":
            confirmation_id = entry.get("值班确认单")
            if confirmation_id is not None:
                guard.write_operation_log(
                    module=self.MODULE,
                    action="确认下水",
                    result="通过",
                    message=(
                        f"潜水记录{entry_id}关联值班确认单{confirmation_id}，"
                        f"潜水员「{entry.get('潜水员')}」、安全员「{entry.get('安全员')}」"
                        "资格核验通过，准予下水"
                    ),
                    shift=entry.get("作业时段"),
                    entry_id=entry_id,
                    operator=operator,
                )
                confirmation = guard.get_confirmation(int(confirmation_id))
                if confirmation is not None:
                    confirmation["diving_record_id"] = entry_id

        if action == "完成作业":
            confirmation_id = entry.get("值班确认单")
            if confirmation_id is not None:
                guard.close_safety_in_transit(
                    int(confirmation_id), f"潜水记录{entry_id}已完成作业"
                )

        # 中止潜水后核销受影响的值班签认资格，并保留排班可用性标记
        if action == "中止潜水":
            self._abort_duty_qualifications(entry, operator)
            self._update_crew_availability(
                str(entry.get("潜水员", "")), str(entry.get("安全员", ""))
            )

        return entry, f"{self.ENTITY}已{action}"

    def _launch_blocker(self, entry: dict[str, Any], operator: str | None) -> str | None:
        confirmation_id = entry.get("值班确认单")
        if confirmation_id is None:
            guard.write_operation_log(
                module=self.MODULE,
                action="确认下水",
                result="拒绝",
                message=f"潜水记录{entry['id']}未关联值班确认单，不能登记下水",
                shift=entry.get("作业时段"),
                entry_id=entry["id"],
                operator=operator,
            )
            return "该潜水记录未关联值班确认单，不能登记下水"
        confirmation = guard.get_confirmation(int(confirmation_id))
        if confirmation is None or confirmation.get("status") == guard.CONFIRM_REVOKED:
            guard.write_operation_log(
                module=self.MODULE,
                action="确认下水",
                result="拒绝",
                message=(
                    f"潜水记录{entry['id']}所持值班确认单{confirmation_id}"
                    "已核销，已中止/失效的旧值班确认不能再次登记下水"
                ),
                shift=entry.get("作业时段"),
                entry_id=entry["id"],
                operator=operator,
            )
            return (
                f"值班确认单{confirmation_id}已核销，"
                "已中止的作业不能凭旧值班确认再次登记下水，请重新生成确认单"
            )
        try:
            guard.validate_launch_qualification(
                str(entry.get("作业时段", "")),
                str(entry.get("潜水员", "")),
                str(entry.get("安全员", "")),
                operator=operator,
            )
        except guard.DutyRuleError as exc:
            return str(exc)
        return None

    def _abort_duty_qualifications(self, entry: dict[str, Any], operator: str | None) -> None:
        confirmation_id = entry.get("值班确认单")
        reason = f"潜水记录{entry['id']}已中止，受影响的值班签认资格核销"
        if confirmation_id is not None:
            guard.revoke_confirmation(
                int(confirmation_id),
                reason,
                operator=operator or "潜水作业",
                revoke_schedules=True,
            )
        else:
            # 兼容未关联确认单的历史数据：按排班行核销资格
            schedule_ids = [
                int(entry[field]) for field in ("diver_schedule_id", "safety_schedule_id")
                if entry.get(field) is not None
            ]
            guard.revoke_schedule_qualifications(schedule_ids, reason)

    def _update_crew_availability(self, diver_name: str, safety_name: str) -> None:
        """潜水中止后更新队员排班的人员可用性。"""
        crew_rows = store.rows("crew_schedule")
        for row in crew_rows:
            member = row.get("队员姓名", "")
            if member in (diver_name, safety_name):
                row["unavailable"] = True
                row["unavailable_reason"] = f"潜水作业中止，{member}需重新评估状态"
                row["diving_aborted"] = True

    def is_diver_available(self, diver_name: str) -> bool:
        """检查潜水员是否可用。"""
        crew_rows = store.find_by("crew_schedule", "队员姓名", diver_name)
        if not crew_rows:
            return True
        return all(not r.get("unavailable", False) for r in crew_rows)
