# -*- coding: utf-8 -*-
"""值班确认单与潜水下水核验的端到端规则测试。

按业务剧本操作：
- 甲、乙两个作业时段，两张含同名队员（张涛）的排班表；
- 先试同一人兼岗（不予受理），再交错签认并演练安全员在途确认与领队交接冲突；
- 换安全员（调整排班核销旧资格 → 重新生成确认单补签）；
- 办完中止后用旧值班单重送下水记录（必须被拒绝）。
"""
from __future__ import annotations

import pytest

from app.services import duty_guard as guard
from app.store import store


@pytest.fixture(autouse=True)
def reset_store():
    store.reset()
    yield


def _crew(schedule_id: int) -> dict:
    row = store.find("crew_schedule", schedule_id)
    assert row is not None
    return row


def _sign(conf_id: int, action: str, operator: str, schedule_id: int):
    from app.services.duty_confirmation import DutyConfirmationService
    return DutyConfirmationService().run_action(
        conf_id, action, operator=operator, schedule_id=schedule_id,
    )


def _create_dive(shift: str, diver: str, safety: str):
    from app.services.diving_ops import DivingOpsService
    svc = DivingOpsService()
    return svc.create_entry({
        "潜水地点": "南海一号站位",
        "潜水深度": "18m",
        "潜水时长": "40min",
        "作业时段": shift,
        "潜水员": diver,
        "安全员": safety,
    })


# ============================================================
# 1. 同一人兼任两个责任岗位不予受理（核对同一作业时段）
# ============================================================
def test_same_person_holding_two_roles_is_rejected():
    # 在甲班追加一条让潜水员李潜同时当值班领队的排班，制造同一时段兼岗
    store.rows("crew_schedule").append({
        "id": 100, "status": "已发布", "pending": True, "abnormal": False,
        "队员姓名": "李潜", "岗位职责": "值班领队", "作业时段": "甲班",
        "所属班组": "潜水一组", "休息安排": "", "排班人": "首席科学家",
        "开始日期": "2026-11-28", "备注说明": "制造兼岗冲突",
    })
    from app.services.duty_confirmation import DutyConfirmationService
    entry, missing = DutyConfirmationService().create_entry({"作业时段": "甲班"})
    assert entry is None
    assert any("兼任" in m and "不予受理" in m for m in missing), missing

    # 操作日志留痕
    logs = store.operation_logs(module="duty_confirmation", result="拒绝")
    assert any("兼任" in log["message"] for log in logs)


# ============================================================
# 2. 正常生成确认单：一张单只含一组已核实责任人
# ============================================================
def test_generate_confirmation_binds_actual_scheduled_people():
    from app.services.duty_confirmation import DutyConfirmationService
    svc = DutyConfirmationService()
    entry, missing = svc.create_entry({"作业时段": "甲班"})
    assert missing == [] and entry is not None
    assert entry["潜水员"] == "李潜" and entry["安全员"] == "张涛"
    # 岗位锚定到具体排班行，而不是只记姓名
    roles = {s["role"]: s["schedule_id"] for s in entry["slots"]}
    assert roles[guard.ROLE_DIVER] == 4
    assert roles[guard.ROLE_SAFETY] == 5
    assert roles[guard.ROLE_LEADER] == 6

    # 同一时段重复生成被拒绝（一张有效确认单只含一组责任人）
    again, missing2 = svc.create_entry({"作业时段": "甲班"})
    assert again is None and any("已有" in m for m in missing2)


# ============================================================
# 3. 同名队员跨排班/跨时段/角色不匹配不能代签
# ============================================================
def test_same_name_member_cannot_cross_sign():
    from app.services.duty_confirmation import DutyConfirmationService
    svc = DutyConfirmationService()
    entry, _ = svc.create_entry({"作业时段": "甲班"})
    conf_id = entry["id"]

    # 乙班的张涛（潜水员，排班7）试图签甲班安全员（排班5）
    blocked, msg = _sign(conf_id, "安全员在途确认", "张涛", 7)
    assert blocked is None
    assert "不是本确认单" in msg or "岗位" in msg

    # 甲班安全员张涛拿乙班自己的排班7来签，仍因排班不对应被拒
    blocked, msg = _sign(conf_id, "安全员在途确认", "张涛", 7)
    assert blocked is None

    # 角色不匹配：甲班潜水员李潜拿潜水员排班4去签安全员
    blocked, msg = _sign(conf_id, "安全员在途确认", "李潜", 4)
    assert blocked is None and "角色" in msg or "岗位" in msg

    # 非排班本人冒名（姓名对不上排班5的张涛）
    blocked, msg = _sign(conf_id, "安全员在途确认", "王领队", 5)
    assert blocked is None and "同名也不能代签" in msg

    # 正确的本人+对应排班可以签
    ok, msg = _sign(conf_id, "潜水员签认", "李潜", 4)
    assert ok is not None, msg
    ok, msg = _sign(conf_id, "安全员在途确认", "张涛", 5)
    assert ok is not None, msg
    assert ok["status"] == guard.CONFIRM_VERIFIED


# ============================================================
# 4. 交错签认：安全员在途确认与领队交接冲突，日志可查谁继续/谁补签
# ============================================================
def test_safety_in_transit_conflicts_with_leader_handover():
    from app.services.duty_confirmation import DutyConfirmationService
    svc = DutyConfirmationService()
    entry, _ = svc.create_entry({"作业时段": "甲班"})
    conf_id = entry["id"]

    _sign(conf_id, "潜水员签认", "李潜", 4)
    _sign(conf_id, "安全员在途确认", "张涛", 5)

    # 安全员已在途，领队交接发生冲突
    blocked, msg = _sign(conf_id, "领队交接", "王领队", 6)
    assert blocked is None
    assert "冲突" in msg and "补签" in msg

    conflict_logs = store.operation_logs(module="duty_confirmation", result="冲突")
    assert conflict_logs, "冲突必须写入操作日志"
    latest = conflict_logs[0]
    assert any("安全员" in name and "继续" in name for name in latest["can_continue"])
    assert any("值班领队" in name and "补签" in name for name in latest["need_resign"])

    # 反向顺序：先领队交接，再安全员在途，也应冲突
    entry_b, _ = DutyConfirmationService().create_entry({"作业时段": "乙班"})
    conf_b = entry_b["id"]
    _sign(conf_b, "潜水员签认", "张涛", 7)
    _sign(conf_b, "领队交接", "陈领队", 9)
    blocked, msg = _sign(conf_b, "安全员在途确认", "赵安", 8)
    assert blocked is None and "冲突" in msg
    logs_b = [l for l in store.operation_logs(result="冲突") if l["entry_id"] == conf_b]
    assert any("需" in "".join(logs_b[0]["need_resign"]) for _ in [0])
    assert any("安全员" in n for n in logs_b[0]["need_resign"])


# ============================================================
# 5. 下水登记必须关联两名实际有资格的队员
# ============================================================
def test_launch_requires_two_qualified_members():
    from app.services.duty_confirmation import DutyConfirmationService
    entry, _ = DutyConfirmationService().create_entry({"作业时段": "甲班"})
    conf_id = entry["id"]

    # 未签认时下水被拒
    dive, missing = _create_dive("甲班", "李潜", "张涛")
    assert dive is None and any("资格缺失" in m or "补签" in m for m in missing)

    _sign(conf_id, "潜水员签认", "李潜", 4)
    # 只签一个岗位仍不行
    dive, missing = _create_dive("甲班", "李潜", "张涛")
    assert dive is None

    _sign(conf_id, "安全员在途确认", "张涛", 5)
    dive, missing = _create_dive("甲班", "李潜", "张涛")
    assert missing == [] and dive is not None
    assert dive["值班确认单"] == conf_id

    # 同一人兼两个岗位登记下水不予受理
    bad, missing = _create_dive("甲班", "李潜", "李潜")
    assert bad is None and any("兼任" in m for m in missing)

    # 姓名与确认单已核实责任人不一致不能借用资格
    bad, missing = _create_dive("甲班", "张涛", "张涛")
    assert bad is None


def test_no_confirmation_shift_cannot_launch():
    dive, missing = _create_dive("不存在的丙班", "李潜", "张涛")
    assert dive is None and any("值班确认单" in m for m in missing)


# ============================================================
# 6. 换安全员：调整排班核销旧资格，重新签认后才能再下水
# ============================================================
def test_schedule_adjustment_revokes_qualification_and_resign():
    from app.services.crew_schedule import CrewScheduleService
    from app.services.duty_confirmation import DutyConfirmationService

    entry, _ = DutyConfirmationService().create_entry({"作业时段": "甲班"})
    conf_id = entry["id"]
    _sign(conf_id, "潜水员签认", "李潜", 4)
    _sign(conf_id, "安全员在途确认", "张涛", 5)
    dive, _ = _create_dive("甲班", "李潜", "张涛")
    assert dive is not None

    # 换安全员：调整甲班安全员排班5
    adjusted, msg = CrewScheduleService().run_action(5, "调整排班", operator="首席科学家")
    assert adjusted is not None and adjusted["status"] == "已调整"

    confirmation = guard.get_confirmation(conf_id)
    safety_slot = next(s for s in confirmation["slots"] if s["role"] == guard.ROLE_SAFETY)
    assert safety_slot["revoked"] is True
    assert confirmation["status"] == guard.CONFIRM_PARTIAL

    # 旧资格下水被拒
    blocked, missing = _create_dive("甲班", "李潜", "张涛")
    assert blocked is None

    # 补一条新安全员排班并重新生成/补签
    new_id = max(r["id"] for r in store.rows("crew_schedule")) + 1
    store.rows("crew_schedule").append({
        "id": new_id, "status": "已发布", "pending": True, "abnormal": False,
        "队员姓名": "孙安", "岗位职责": "安全员", "作业时段": "甲班",
        "所属班组": "潜水一组", "休息安排": "", "排班人": "首席科学家",
        "开始日期": "2026-11-28", "备注说明": "接替张涛的新安全员",
    })
    # 原确认单已部分核销，先整体核销再按新排班生成
    DutyConfirmationService().run_action(conf_id, "核销确认单", operator="王领队")
    new_conf, _ = DutyConfirmationService().create_entry({"作业时段": "甲班"})
    assert new_conf is not None and new_conf["id"] != conf_id
    _sign(new_conf["id"], "潜水员签认", "李潜", 4)
    _sign(new_conf["id"], "安全员在途确认", "孙安", new_id)

    dive2, missing = _create_dive("甲班", "李潜", "孙安")
    assert missing == [] and dive2 is not None


# ============================================================
# 7. 潜水中止核销资格，旧值班单不能再次登记下水
# ============================================================
def test_aborted_dive_cannot_relaunch_with_old_confirmation():
    from app.services.diving_ops import DivingOpsService
    from app.services.duty_confirmation import DutyConfirmationService

    entry, _ = DutyConfirmationService().create_entry({"作业时段": "甲班"})
    conf_id = entry["id"]
    _sign(conf_id, "潜水员签认", "李潜", 4)
    _sign(conf_id, "安全员在途确认", "张涛", 5)
    dive, _ = _create_dive("甲班", "李潜", "张涛")
    dive_id = dive["id"]

    diving_svc = DivingOpsService()
    launched, msg = diving_svc.run_action(dive_id, "确认下水", operator="张涛")
    assert launched is not None and launched["status"] == "已下水"

    aborted, msg = diving_svc.run_action(dive_id, "中止潜水", operator="王领队")
    assert aborted is not None and aborted["status"] == "已中止"

    confirmation = guard.get_confirmation(conf_id)
    assert confirmation["status"] == guard.CONFIRM_REVOKED
    # 关联排班资格同步核销
    assert _crew(4)["qualification_revoked"] is True
    assert _crew(5)["qualification_revoked"] is True

    # 旧确认单上的记录不能再次确认下水
    blocked, msg = diving_svc.run_action(dive_id, "确认下水", operator="张涛")
    assert blocked is None and "旧值班确认" in msg

    # 用同一份旧值班单重新送一条下水登记也被拒
    again, missing = _create_dive("甲班", "李潜", "张涛")
    assert again is None
    assert any("核销" in m or "旧值班确认" in m or "补签" in m for m in missing)

    # 操作日志能完整追溯
    logs = store.operation_logs(shift="甲班")
    actions = {log["action"] for log in logs}
    assert "确认下水" in actions and "核销确认单" in actions


# ============================================================
# 8. 操作日志可按模块/时段/结果过滤，呈现谁可继续、谁需补签
# ============================================================
def test_operation_log_query_filters():
    from app.services.duty_confirmation import DutyConfirmationService
    entry, _ = DutyConfirmationService().create_entry({"作业时段": "甲班"})
    conf_id = entry["id"]
    _sign(conf_id, "潜水员签认", "李潜", 4)
    _sign(conf_id, "安全员在途确认", "张涛", 5)
    _sign(conf_id, "领队交接", "王领队", 6)  # 冲突

    rejected = store.operation_logs(result="冲突")
    assert rejected and all(r["result"] == "冲突" for r in rejected)
    jia = store.operation_logs(shift="甲班")
    assert all(r["shift"] == "甲班" for r in jia)
    only_conf = store.operation_logs(module="duty_confirmation", entry_id=conf_id)
    assert only_conf and all(r["entry_id"] == conf_id for r in only_conf)


# ============================================================
# 9. 乙班同名张涛以潜水员身份独立签认，两套资格互不串用
# ============================================================
def test_two_shifts_same_name_keep_independent_qualifications():
    from app.services.duty_confirmation import DutyConfirmationService
    svc = DutyConfirmationService()
    jia, _ = svc.create_entry({"作业时段": "甲班"})
    yi, _ = svc.create_entry({"作业时段": "乙班"})

    _sign(jia["id"], "潜水员签认", "李潜", 4)
    _sign(jia["id"], "安全员在途确认", "张涛", 5)
    _sign(yi["id"], "潜水员签认", "张涛", 7)
    _sign(yi["id"], "安全员在途确认", "赵安", 8)

    # 甲班张涛是安全员，乙班张涛是潜水员，各自锚定不同排班行
    jia_safety = next(s for s in jia["slots"] if s["role"] == guard.ROLE_SAFETY)
    yi_diver = next(s for s in yi["slots"] if s["role"] == guard.ROLE_DIVER)
    assert jia_safety["schedule_id"] == 5 and yi_diver["schedule_id"] == 7

    dive_jia, missing = _create_dive("甲班", "李潜", "张涛")
    dive_yi, missing_yi = _create_dive("乙班", "张涛", "赵安")
    assert dive_jia is not None and dive_yi is not None
    assert dive_jia["值班确认单"] != dive_yi["值班确认单"]
