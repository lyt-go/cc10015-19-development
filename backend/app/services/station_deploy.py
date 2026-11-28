"""站位布设领域服务：布设站位需校验航次计划状态、气象海况和人员可用性。
支持事务回滚和重试恢复。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class StationDeployService(BaseModuleService):
    MODULE = "station_deploy"
    ENTITY = "站位记录"
    OPERATION_TERM = "确认站位"
    LIST_FIELDS = ["站位编号", "经纬度坐标", "水深数据", "采样类型", "计划作业时间", "实际作业时间", "布设人", "备注说明"]
    REQUIRED_FIELDS = ["站位编号", "经纬度坐标", "水深数据"]
    STATUS_ORDER = ["待布设", "已布设", "已作业", "已跳过"]
    ACTION_RULES = {"确认站位": "已布设", "开始作业": "已作业", "跳过站位": "已跳过"}
    NEGATIVE_ACTIONS = ["跳过站位"]

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

        target = self.ACTION_RULES.get(action)
        if target is None:
            return None, f"动作「{action}」不属于{self.MODULE}可执行范围"

        # 幂等检查
        idempotent_key = f"{self.MODULE}:{entry_id}:{action}"
        if store.is_idempotent(idempotent_key):
            return None, f"动作「{action}」已执行，请勿重复操作"

        # 站位布设前置条件：检查航次计划是否已批准
        if action == "确认站位":
            cruise_rows = store.rows("cruise_plan")
            if not any(r.get("status") == "已批准" for r in cruise_rows):
                return None, "航次计划尚未批准，无法布设站位"

        # 站位作业前置条件：检查是否有恶劣海况
        if action == "开始作业":
            weather_rows = store.rows("weather_obs")
            severe_weather = any(r.get("status") == "恶劣海况" for r in weather_rows)
            if severe_weather:
                return None, "当前存在恶劣海况标记，无法开始站位作业"
            # 检查布设人是否可用（受排班和潜水影响）
            deployer = entry.get("布设人", "")
            if deployer:
                crew_rows = store.find_by("crew_schedule", "队员姓名", deployer)
                for crew in crew_rows:
                    if crew.get("unavailable") or crew.get("diving_aborted"):
                        return None, f"布设人「{deployer}」当前不可用（受排班/潜水中止影响）"

        # 保存操作前快照，支持回滚
        tx_id = f"{self.MODULE}:{entry_id}:{action}:tx"
        store.save_snapshot(tx_id, self.MODULE, entry_id)

        old_status = entry.get("status")
        entry["status"] = target
        entry["pending"] = target in ("待布设", "已布设")
        entry["abnormal"] = action in self.NEGATIVE_ACTIONS
        entry["action_timestamp"] = str(Any)

        store.mark_idempotent(idempotent_key)

        return entry, f"{self.ENTITY}已{action}"

    def get_operable_stations(self) -> list[dict[str, Any]]:
        """返回当前可作业的站位列表（排除恶劣海况和人员不足影响）。"""
        weather_rows = store.rows("weather_obs")
        severe = any(r.get("status") == "恶劣海况" for r in weather_rows)
        rows = store.rows(self.MODULE)
        operable = []
        for r in rows:
            if severe and r.get("status") not in ("待布设", "已布设"):
                continue
            if r.get("status") == "已跳过":
                continue
            # 检查布设人可用性
            deployer = r.get("布设人", "")
            if deployer:
                crew_rows = store.find_by("crew_schedule", "队员姓名", deployer)
                for crew in crew_rows:
                    if crew.get("unavailable") or crew.get("diving_aborted"):
                        r["crew_blocked"] = True
                        r["crew_block_reason"] = f"布设人{deployer}不可用"
            operable.append(r)
        return operable