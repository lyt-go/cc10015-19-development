# -*- coding: utf-8 -*-
"""值班核验领域规则。

把"队员排班 → 值班确认单 → 潜水下水登记"的资格链集中在这里：

1. 值班确认单只能由当前排班（已发布/已确认且未调整、未核销）的实际签认人生成；
2. 任一岗位的签认锚定到具体排班行 id，同名队员跨排班、跨时段不能代签；
3. 同一作业时段内同一队员兼任两个责任岗位不予受理；
4. 安全员在途确认与值班领队交接互斥，冲突与可继续确认/需补签的人员写入操作日志；
5. 排班调整、潜水中止会核销受影响的签认资格，中止后的旧确认单不能再次登记下水；
6. 一张有效确认单只承载一组已核实的当班责任人（一名潜水员、一名安全员）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

ROLE_DIVER = "潜水员"
ROLE_SAFETY = "安全员"
ROLE_LEADER = "值班领队"
RESPONSIBLE_ROLES = (ROLE_DIVER, ROLE_SAFETY, ROLE_LEADER)

# 只有已发布或已确认、且未被调整/核销的排班行才能产生有效签认资格
VALID_SCHEDULE_STATUSES = ("已发布", "已确认")

CONFIRM_PENDING = "待签认"
CONFIRM_PARTIAL = "部分签认"
CONFIRM_VERIFIED = "已核实"
CONFIRM_REVOKED = "已核销"

SLOT_PENDING = "待签认"
SLOT_SIGNED = "已签认"
SLOT_REVOKED = "已核销"


class DutyRuleError(Exception):
    """值班规则校验失败。``logged=True`` 表示调用方已经写过操作日志。"""

    def __init__(self, message: str, *, logged: bool = False) -> None:
        super().__init__(message)
        self.logged = logged


# ------------------------------------------------------------------
# 基础工具
# ------------------------------------------------------------------
def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _next_id(module: str) -> int:
    return max((int(row.get("id", 0)) for row in store.rows(module)), default=0) + 1


def _person_desc(schedule_row: dict[str, Any]) -> str:
    """生成带排班身份的人员描述，避免同名队员混淆。"""
    return (
        f"{schedule_row.get('队员姓名', '')}"
        f"（{schedule_row.get('岗位职责', '')}/排班{schedule_row.get('id')}/"
        f"{schedule_row.get('作业时段', '')}）"
    )


def write_operation_log(
    *,
    module: str,
    action: str,
    result: str,
    message: str,
    shift: str | None = None,
    entry_id: int | None = None,
    operator: str | None = None,
    role: str | None = None,
    schedule_id: int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把一次值班核验操作（含被拒绝的操作）写入操作日志。"""
    record: dict[str, Any] = {
        "time": _now(),
        "module": module,
        "entry_id": entry_id,
        "action": action,
        "result": result,  # 通过 / 拒绝 / 核销 / 冲突
        "shift": shift,
        "operator": operator,
        "role": role,
        "schedule_id": schedule_id,
        "message": message,
    }
    if extra:
        record.update(extra)
    return store.append_operation_log(record)


# ------------------------------------------------------------------
# 排班查询
# ------------------------------------------------------------------
def shift_roster(shift: str) -> list[dict[str, Any]]:
    """返回某作业时段当前仍有效的责任岗位排班行（已发布/已确认、未调整、未核销）。"""
    return [
        row
        for row in store.rows("crew_schedule")
        if str(row.get("作业时段", "")) == str(shift)
        and row.get("岗位职责") in RESPONSIBLE_ROLES
        and row.get("status") in VALID_SCHEDULE_STATUSES
        and not row.get("qualification_revoked")
    ]


def find_schedule_row(schedule_id: int) -> dict[str, Any] | None:
    return store.find("crew_schedule", schedule_id)


def schedule_is_valid(schedule_row: dict[str, Any]) -> bool:
    """排班行是否仍能支撑有效签认资格。"""
    return (
        schedule_row.get("status") in VALID_SCHEDULE_STATUSES
        and not schedule_row.get("qualification_revoked")
    )


# ------------------------------------------------------------------
# 值班确认单生成
# ------------------------------------------------------------------
def create_confirmation(shift: str, operator: str | None = None) -> dict[str, Any]:
    """按作业时段从当前排班生成一张值班确认单。

    同一时段存在一张未核销确认单时直接复用，保证"一张有效确认单只含一组责任人"。
    """
    shift = str(shift).strip()
    if not shift:
        raise DutyRuleError("作业时段不能为空，无法生成值班确认单")

    existing = active_confirmation_for_shift(shift)
    if existing is not None:
        write_operation_log(
            module="duty_confirmation",
            action="生成确认单",
            result="拒绝",
            message=f"作业时段{shift}已有未核销的值班确认单{existing['id']}，一张有效确认单只能包含一组当班责任人",
            shift=shift,
            entry_id=existing["id"],
            operator=operator,
        )
        raise DutyRuleError(
            f"作业时段{shift}已有有效值班确认单（单号{existing['id']}），不能重复生成",
            logged=True,
        )

    roster = shift_roster(shift)
    if not roster:
        raise DutyRuleError(f"作业时段{shift}没有已发布/已确认的责任岗位排班，无法生成值班确认单")

    # 同一人兼任两个责任岗位不予受理（按姓名核对同一作业时段），优先于岗位唯一性检查
    name_roles: dict[str, list[str]] = {}
    for row in roster:
        name = str(row.get("队员姓名", "")).strip()
        if name:
            name_roles.setdefault(name, []).append(str(row.get("岗位职责")))
    for name, roles in name_roles.items():
        if len(roles) > 1:
            write_operation_log(
                module="duty_confirmation",
                action="生成确认单",
                result="拒绝",
                message=(
                    f"作业时段{shift}内队员「{name}」同时承担{'、'.join(roles)}，"
                    "同一人兼任两个责任岗位不予受理"
                ),
                shift=shift,
                operator=operator,
            )
            raise DutyRuleError(
                f"同一作业时段内「{name}」兼任{'、'.join(roles)}，不予受理，请重新排班",
                logged=True,
            )

    role_rows: dict[str, dict[str, Any]] = {}
    duplicates: dict[str, list[int]] = {}
    for row in roster:
        role = str(row.get("岗位职责"))
        if role in role_rows:
            duplicates.setdefault(role, [role_rows[role]["id"]]).append(int(row["id"]))
        else:
            role_rows[role] = row
    if duplicates:
        detail = "；".join(
            f"{role}存在多条排班（排班{'、'.join(str(i) for i in ids)}），请先调整排班"
            for role, ids in duplicates.items()
        )
        raise DutyRuleError(f"作业时段{shift}同一岗位排班不唯一：{detail}")

    missing = [role for role in (ROLE_DIVER, ROLE_SAFETY) if role not in role_rows]
    if missing:
        raise DutyRuleError(
            f"作业时段{shift}排班缺少{ '、'.join(missing) }，无法生成值班确认单"
        )

    names = {role: str(row.get("队员姓名", "")).strip() for role, row in role_rows.items()}

    slots = []
    for role in RESPONSIBLE_ROLES:
        row = role_rows.get(role)
        if row is None:
            continue
        slots.append(
            {
                "role": role,
                "schedule_id": int(row["id"]),
                "member_name": row.get("队员姓名", ""),
                "shift": shift,
                "status": SLOT_PENDING,
                "signed_by": None,
                "signed_at": None,
                "revoked": False,
                "revoke_reason": None,
            }
        )

    entry = {
        "id": _next_id("duty_confirmation"),
        "status": CONFIRM_PENDING,
        "pending": True,
        "abnormal": False,
        "作业时段": shift,
        "确认单编号": f"DUTY-{shift}-{_next_id('duty_confirmation'):04d}",
        "潜水员": names.get(ROLE_DIVER, ""),
        "安全员": names.get(ROLE_SAFETY, ""),
        "值班领队": names.get(ROLE_LEADER, ""),
        "关联排班": sorted(int(row["id"]) for row in role_rows.values()),
        "slots": slots,
        "safety_in_transit": False,
        "leader_handed_over": False,
        "diving_record_id": None,
        "备注说明": "",
    }
    store.rows("duty_confirmation").append(entry)
    write_operation_log(
        module="duty_confirmation",
        action="生成确认单",
        result="通过",
        message=(
            f"已按作业时段{shift}的当前排班生成值班确认单{entry['id']}，"
            f"当班责任人：{_person_desc(role_rows[ROLE_DIVER])}、"
            f"{_person_desc(role_rows[ROLE_SAFETY])}"
        ),
        shift=shift,
        entry_id=entry["id"],
        operator=operator,
    )
    return entry


def active_confirmation_for_shift(shift: str) -> dict[str, Any] | None:
    """返回该时段当前未核销的确认单。"""
    for row in store.rows("duty_confirmation"):
        if str(row.get("作业时段", "")) == str(shift) and row.get("status") != CONFIRM_REVOKED:
            return row
    return None


def get_confirmation(entry_id: int) -> dict[str, Any] | None:
    return store.find("duty_confirmation", entry_id)


def _slot_of(entry: dict[str, Any], role: str) -> dict[str, Any] | None:
    for slot in entry.get("slots", []):
        if slot.get("role") == role:
            return slot
    return None


# ------------------------------------------------------------------
# 岗位签认
# ------------------------------------------------------------------
def sign_slot(
    entry_id: int,
    role: str,
    operator: str,
    schedule_id: int,
    *,
    action_label: str,
) -> dict[str, Any]:
    """由负责该作业时段且角色匹配的排班人办理岗位签认。"""
    operator = str(operator or "").strip()
    if not operator:
        raise DutyRuleError("缺少办理人姓名，无法签认")
    if role not in RESPONSIBLE_ROLES:
        raise DutyRuleError(f"未知责任岗位：{role}")

    entry = get_confirmation(entry_id)
    if entry is None:
        raise DutyRuleError(f"值班确认单 {entry_id} 不存在或已归档")
    if entry.get("status") == CONFIRM_REVOKED:
        raise DutyRuleError(f"值班确认单{entry_id}已核销，不能再签认")

    shift = entry.get("作业时段")
    slot = _slot_of(entry, role)
    if slot is None:
        raise DutyRuleError(f"值班确认单{entry_id}没有{role}岗位，无法签认")
    if slot.get("revoked") or slot.get("status") == SLOT_REVOKED:
        raise DutyRuleError(f"{role}的签认资格已核销，需重新生成值班确认单后补签")
    if slot.get("status") == SLOT_SIGNED:
        raise DutyRuleError(
            f"{role}岗位已由{slot.get('signed_by')}签认，请勿重复操作"
        )

    schedule_row = find_schedule_row(int(schedule_id))
    if schedule_row is None:
        _reject(
            entry, role, operator, schedule_id, action_label,
            f"排班{schedule_id}不存在，办理人「{operator}」没有该时段的有效签认资格",
        )
    assert schedule_row is not None

    if int(schedule_row.get("id", 0)) != int(slot["schedule_id"]):
        _reject(
            entry, role, operator, schedule_id, action_label,
            (
                f"办理人「{operator}」所持排班{schedule_id}不是本确认单{role}岗位"
                f"对应的排班{slot['schedule_id']}，不能跨排班代签"
            ),
        )
    if str(schedule_row.get("作业时段", "")) != str(shift):
        _reject(
            entry, role, operator, schedule_id, action_label,
            (
                f"排班{schedule_id}属于作业时段{schedule_row.get('作业时段')}，"
                f"与确认单时段{shift}不一致，不能跨时段签认"
            ),
        )
    if str(schedule_row.get("岗位职责", "")) != role:
        _reject(
            entry, role, operator, schedule_id, action_label,
            (
                f"办理人「{operator}」在排班{schedule_id}中的岗位是"
                f"{schedule_row.get('岗位职责')}，与{role}不匹配，不能角色越权签认"
            ),
        )
    if str(schedule_row.get("队员姓名", "")).strip() != operator:
        _reject(
            entry, role, operator, schedule_id, action_label,
            (
                f"排班{schedule_id}的实际签认人是{schedule_row.get('队员姓名')}，"
                f"办理人「{operator}」同名也不能代签"
            ),
        )
    if not schedule_is_valid(schedule_row):
        _reject(
            entry, role, operator, schedule_id, action_label,
            (
                f"排班{schedule_id}当前状态为{schedule_row.get('status')}"
                + ("（资格已核销）" if schedule_row.get("qualification_revoked") else "")
                + "，不具备有效签认资格，需先补排班级别的确认"
            ),
        )

    # 安全员在途确认 与 值班领队交接 互斥
    conflict = _conflict_message(entry, role)
    if conflict is not None:
        write_operation_log(
            module="duty_confirmation",
            action=action_label,
            result="冲突",
            message=conflict,
            shift=shift,
            entry_id=entry_id,
            operator=operator,
            role=role,
            schedule_id=schedule_id,
            extra={
                "can_continue": _who_can_continue(entry, role),
                "need_resign": _who_must_resign(entry, role),
            },
        )
        raise DutyRuleError(conflict, logged=True)

    slot["status"] = SLOT_SIGNED
    slot["signed_by"] = operator
    slot["signed_at"] = _now()
    slot["schedule_id"] = int(schedule_id)
    if role == ROLE_SAFETY:
        entry["safety_in_transit"] = True
    if role == ROLE_LEADER:
        entry["leader_handed_over"] = True

    _refresh_confirmation_status(entry)
    write_operation_log(
        module="duty_confirmation",
        action=action_label,
        result="通过",
        message=(
            f"{role}岗位签认通过：{_person_desc(schedule_row)}办理{action_label}；"
            f"确认单{entry_id}当前状态{entry['status']}"
        ),
        shift=shift,
        entry_id=entry_id,
        operator=operator,
        role=role,
        schedule_id=schedule_id,
        extra={
            "can_continue": _who_can_continue(entry, role),
            "need_resign": _who_must_resign(entry, role),
        },
    )
    return entry


def _reject(
    entry: dict[str, Any],
    role: str,
    operator: str,
    schedule_id: int,
    action_label: str,
    message: str,
) -> None:
    write_operation_log(
        module="duty_confirmation",
        action=action_label,
        result="拒绝",
        message=message,
        shift=entry.get("作业时段"),
        entry_id=entry.get("id"),
        operator=operator,
        role=role,
        schedule_id=schedule_id,
    )
    raise DutyRuleError(message, logged=True)


def _conflict_message(entry: dict[str, Any], role: str) -> str | None:
    """安全员在途确认与值班领队交接发生冲突时返回说明，否则返回 None。"""
    if role == ROLE_SAFETY and entry.get("leader_handed_over"):
        leader_slot = _slot_of(entry, ROLE_LEADER)
        leader = leader_slot.get("signed_by") if leader_slot else "值班领队"
        return (
            f"值班领队「{leader}」已完成交接，安全员在途确认与其冲突，"
            f"安全员「{entry.get('安全员')}」需待新一轮值班确认补签"
        )
    if role == ROLE_LEADER and entry.get("safety_in_transit"):
        safety_slot = _slot_of(entry, ROLE_SAFETY)
        safety = safety_slot.get("signed_by") if safety_slot else "安全员"
        return (
            f"安全员「{safety}」已作在途确认，值班领队交接与其冲突，"
            f"安全员可继续在途确认，值班领队需补签交接"
        )
    return None


def _who_can_continue(entry: dict[str, Any], acting_role: str) -> list[str]:
    """冲突/签认后仍可继续办理的人员描述。"""
    names: list[str] = []
    if acting_role == ROLE_LEADER and entry.get("safety_in_transit"):
        slot = _slot_of(entry, ROLE_SAFETY)
        if slot and slot.get("signed_by"):
            names.append(f"{slot['signed_by']}（安全员，可继续在途确认）")
    elif acting_role == ROLE_SAFETY and entry.get("leader_handed_over"):
        slot = _slot_of(entry, ROLE_LEADER)
        if slot and slot.get("signed_by"):
            names.append(f"{slot['signed_by']}（值班领队，交接已成立）")
    else:
        for slot in entry.get("slots", []):
            if slot.get("status") == SLOT_SIGNED and not slot.get("revoked"):
                names.append(f"{slot.get('signed_by')}（{slot.get('role')}，签认有效）")
    return names


def _who_must_resign(entry: dict[str, Any], acting_role: str) -> list[str]:
    """冲突后需要补签的人员描述。"""
    names: list[str] = []
    if acting_role == ROLE_LEADER and entry.get("safety_in_transit"):
        leader = _slot_of(entry, ROLE_LEADER)
        name = entry.get("值班领队") or (leader.get("member_name") if leader else "")
        if name:
            names.append(f"{name}（值班领队，需补签交接）")
    if acting_role == ROLE_SAFETY and entry.get("leader_handed_over"):
        safety = _slot_of(entry, ROLE_SAFETY)
        name = entry.get("安全员") or (safety.get("member_name") if safety else "")
        if name:
            names.append(f"{name}（安全员，需在新一轮值班确认补签）")
    return names


def _refresh_confirmation_status(entry: dict[str, Any]) -> None:
    slots = entry.get("slots", [])
    signed = [s for s in slots if s.get("status") == SLOT_SIGNED and not s.get("revoked")]
    revoked = [s for s in slots if s.get("revoked") or s.get("status") == SLOT_REVOKED]
    core_roles = {s.get("role") for s in signed if s.get("role") in (ROLE_DIVER, ROLE_SAFETY)}
    if revoked and not signed:
        entry["status"] = CONFIRM_REVOKED
    elif {ROLE_DIVER, ROLE_SAFETY}.issubset(core_roles):
        entry["status"] = CONFIRM_VERIFIED
    elif signed:
        entry["status"] = CONFIRM_PARTIAL
    else:
        entry["status"] = CONFIRM_PENDING
    entry["pending"] = entry["status"] != CONFIRM_REVOKED


# ------------------------------------------------------------------
# 资格核销
# ------------------------------------------------------------------
def revoke_schedule_qualifications(schedule_ids: list[int], reason: str) -> list[dict[str, Any]]:
    """排班调整后核销受影响排班行的签认资格，并联动其所在确认单。"""
    affected_entries: list[dict[str, Any]] = []
    for schedule_id in schedule_ids:
        row = find_schedule_row(int(schedule_id))
        if row is None:
            continue
        row["qualification_revoked"] = True
        for entry in store.rows("duty_confirmation"):
            if entry.get("status") == CONFIRM_REVOKED:
                continue
            for slot in entry.get("slots", []):
                if int(slot.get("schedule_id", 0)) == int(schedule_id) and not slot.get("revoked"):
                    revoke_slot(entry, slot, reason, operator="队员排班")
                    if entry not in affected_entries:
                        affected_entries.append(entry)
    return affected_entries


def revoke_slot(
    entry: dict[str, Any],
    slot: dict[str, Any],
    reason: str,
    *,
    operator: str,
) -> None:
    """核销确认单上的单个岗位签认资格。"""
    slot["revoked"] = True
    slot["status"] = SLOT_REVOKED
    slot["revoke_reason"] = reason
    if slot.get("role") == ROLE_SAFETY:
        entry["safety_in_transit"] = False
    if slot.get("role") == ROLE_LEADER:
        entry["leader_handed_over"] = False

    signed_remaining = [
        s for s in entry.get("slots", [])
        if not s.get("revoked") and s.get("status") == SLOT_SIGNED
    ]
    if not signed_remaining:
        entry["status"] = CONFIRM_REVOKED
        entry["pending"] = False
        entry["abnormal"] = True
    else:
        entry["status"] = CONFIRM_PARTIAL
        entry["pending"] = True
    write_operation_log(
        module="duty_confirmation",
        action="核销资格",
        result="核销",
        message=(
            f"作业时段{entry.get('作业时段')}确认单{entry.get('id')}的"
            f"{slot.get('role')}岗位（排班{slot.get('schedule_id')}、"
            f"{slot.get('member_name')}）资格已核销：{reason}；"
            f"确认单当前状态{entry['status']}"
        ),
        shift=entry.get("作业时段"),
        entry_id=entry.get("id"),
        operator=operator,
        role=slot.get("role"),
        schedule_id=slot.get("schedule_id"),
        extra={"reason": reason},
    )


def revoke_confirmation(
    entry_id: int,
    reason: str,
    *,
    operator: str,
    revoke_schedules: bool = False,
) -> dict[str, Any] | None:
    """整体核销一张值班确认单。

    ``revoke_schedules=True`` 时同步核销关联排班行的签认资格（潜水中止场景）；
    仅换岗/重开确认单时保留未调整排班的资格，便于重新签认。
    """
    entry = get_confirmation(entry_id)
    if entry is None or entry.get("status") == CONFIRM_REVOKED:
        return entry
    for slot in list(entry.get("slots", [])):
        if not slot.get("revoked"):
            revoke_slot(entry, slot, reason, operator=operator)
    entry["status"] = CONFIRM_REVOKED
    entry["pending"] = False
    entry["abnormal"] = True
    if revoke_schedules:
        for schedule_id in entry.get("关联排班", []):
            row = find_schedule_row(int(schedule_id))
            if row is not None:
                row["qualification_revoked"] = True
                row["unavailable"] = True
                row["unavailable_reason"] = reason
    write_operation_log(
        module="duty_confirmation",
        action="核销确认单",
        result="核销",
        message=f"值班确认单{entry_id}已整体核销：{reason}",
        shift=entry.get("作业时段"),
        entry_id=entry_id,
        operator=operator,
        extra={"reason": reason},
    )
    return entry


def close_safety_in_transit(entry_id: int, reason: str) -> None:
    """潜水结束/中止后关闭安全员在途确认状态（交接结果已落定）。"""
    entry = get_confirmation(entry_id)
    if entry is None:
        return
    if entry.get("safety_in_transit"):
        entry["safety_in_transit"] = False
        write_operation_log(
            module="duty_confirmation",
            action="关闭在途确认",
            result="通过",
            message=f"值班确认单{entry_id}的安全员在途确认已关闭：{reason}",
            shift=entry.get("作业时段"),
            entry_id=entry_id,
            operator="潜水作业",
        )


# ------------------------------------------------------------------
# 下水登记资格核验
# ------------------------------------------------------------------
def _signed_active_slot(entry: dict[str, Any], role: str) -> dict[str, Any] | None:
    slot = _slot_of(entry, role)
    if slot is None or slot.get("revoked") or slot.get("status") != SLOT_SIGNED:
        return None
    row = find_schedule_row(int(slot["schedule_id"]))
    if row is None or not schedule_is_valid(row):
        return None
    return slot


def validate_launch_qualification(
    shift: str,
    diver_name: str,
    safety_name: str,
    *,
    operator: str | None = None,
) -> dict[str, Any]:
    """核验下水登记关联的两名队员是否都具备当前时段的有效签认资格。"""
    shift = str(shift or "").strip()
    diver_name = str(diver_name or "").strip()
    safety_name = str(safety_name or "").strip()

    def fail(message: str) -> None:
        write_operation_log(
            module="diving_ops",
            action="确认下水",
            result="拒绝",
            message=message,
            shift=shift or None,
            operator=operator,
        )
        raise DutyRuleError(message, logged=True)

    if not shift:
        fail("下水登记缺少作业时段，无法核验值班确认单")
    if not diver_name or not safety_name:
        fail("下水登记必须关联潜水员和安全员两名队员")
    if diver_name == safety_name:
        fail(f"「{diver_name}」不能同时担任潜水员和安全员，同一人兼任两个责任岗位不予受理")

    entry = active_confirmation_for_shift(shift)
    if entry is None:
        revoked = [
            row for row in store.rows("duty_confirmation")
            if str(row.get("作业时段", "")) == shift and row.get("status") == CONFIRM_REVOKED
        ]
        if revoked:
            fail(
                f"作业时段{shift}的值班确认单{revoked[-1]['id']}已核销，"
                "已中止/失效的旧值班确认不能再次登记下水，请重新生成确认单并补签"
            )
        fail(f"作业时段{shift}没有有效的值班确认单，请先由当班排班人完成签认")
    assert entry is not None
    if entry.get("status") == CONFIRM_REVOKED:
        fail(f"作业时段{shift}的值班确认单{entry['id']}已核销，旧值班确认不能再次登记下水")

    diver_slot = _signed_active_slot(entry, ROLE_DIVER)
    safety_slot = _signed_active_slot(entry, ROLE_SAFETY)
    if diver_slot is None or safety_slot is None:
        missing_roles = [
            role for role, slot in (
                (ROLE_DIVER, diver_slot), (ROLE_SAFETY, safety_slot),
            ) if slot is None
        ]
        fail(
            f"值班确认单{entry['id']}的{'、'.join(missing_roles)}签认资格缺失或已核销，"
            "需由对应排班人补签后才能登记下水"
        )
    assert diver_slot is not None and safety_slot is not None

    if diver_slot.get("member_name") != diver_name:
        fail(
            f"下水登记潜水员「{diver_name}」与确认单{entry['id']}已核实的"
            f"潜水员{diver_slot.get('member_name')}不一致，不能凭他人资格登记"
        )
    if safety_slot.get("member_name") != safety_name:
        fail(
            f"下水登记安全员「{safety_name}」与确认单{entry['id']}已核实的"
            f"安全员{safety_slot.get('member_name')}不一致，不能凭他人资格登记"
        )
    return entry


def qualification_summary(shift: str | None = None) -> dict[str, Any]:
    """供快照/页面使用的资格汇总。"""
    rows = store.rows("duty_confirmation")
    if shift:
        rows = [r for r in rows if str(r.get("作业时段", "")) == str(shift)]
    return {
        "total": len(rows),
        "verified": sum(1 for r in rows if r.get("status") == CONFIRM_VERIFIED),
        "partial": sum(1 for r in rows if r.get("status") == CONFIRM_PARTIAL),
        "pending": sum(1 for r in rows if r.get("status") == CONFIRM_PENDING),
        "revoked": sum(1 for r in rows if r.get("status") == CONFIRM_REVOKED),
    }
