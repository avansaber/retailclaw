"""A completed return cannot be edited or cancelled; only processing completes.

Covers update_return_authorization guards:
  1. completed returns refuse every change except notes-only edits,
  2. nothing may be set to completed except through retail-process-return,
  3. cancelled returns cannot be reopened.
"""
import pytest

from erpclaw_lib.query import Q, P, Table, Field, fn
from retail_helpers import call_action, ns, is_error, is_ok, load_db_query

mod = load_db_query()


def _completed_msg(return_id):
    return f"Return {return_id} is completed and its refund is posted; it cannot be changed"


COMPLETE_DIRECT_MSG = "A return is completed only by retail-process-return, which posts its refund"


def _cancelled_msg(return_id):
    return f"Return {return_id} is cancelled and cannot be reopened"


def _make_pending(conn, env):
    ra = call_action(mod.retail_add_return_authorization, conn, ns(
        company_id=env["company_id"],
        customer_id=env["customer_id"],
        customer_name="Refusal Customer",
        return_date="2026-03-10",
        reason="Refusal test",
        return_type="refund",
        original_invoice_id=None,
        notes=None,
    ))
    assert is_ok(ra), ra
    rid = ra["id"]
    item = call_action(mod.retail_add_return_item, conn, ns(
        return_id=rid,
        item_id=env["item1"],
        item_name="Widget A",
        qty="2",
        rate="60.00",
        reason=None,
        item_condition="good",
        disposition="restock",
    ))
    assert is_ok(item), item
    return rid


def _make_completed(conn, env):
    rid = _make_pending(conn, env)
    result = call_action(mod.retail_process_return, conn, ns(
        return_id=rid,
        return_status="completed",
        sales_returns_account_id=env["sales_returns_acct"],
        cash_account_id=env["cash_acct"],
        inventory_account_id=None,
        cogs_account_id=None,
        cost_center_id=env["cc"],
        restock_cost=None,
    ))
    assert is_ok(result), result
    assert result["refund_amount"] == "120.00"
    rows = _gl_rows(conn, rid)
    assert len(rows) == 2
    return rid


def _update(conn, rid, **kw):
    params = dict(
        return_id=rid,
        customer_name=None,
        reason=None,
        original_invoice_id=None,
        notes=None,
        return_type=None,
        return_status=None,
        restocking_fee=None,
    )
    params.update(kw)
    return call_action(mod.retail_update_return_authorization, conn, ns(**params))


def _full_row(conn, rid):
    t = Table("retailclaw_return_authorization")
    q = Q.from_(t).select(t.star).where(Field("id") == P())
    return dict(conn.execute(q.get_sql(), (rid,)).fetchone())


def _gl_rows(conn, rid):
    t = Table("gl_entry")
    q = Q.from_(t).select(t.star).where(t.voucher_id == P())
    return [dict(r) for r in conn.execute(q.get_sql(), (rid,)).fetchall()]


def _audit_count(conn):
    t = Table("audit_log")
    q = Q.from_(t).select(fn.Count("*"))
    return conn.execute(q.get_sql(), []).fetchone()[0]


def test_cancel_completed_refused(conn, env):
    rid = _make_completed(conn, env)
    before_row = _full_row(conn, rid)
    before_gl = _gl_rows(conn, rid)
    before_audit = _audit_count(conn)
    result = _update(conn, rid, return_status="cancelled")
    assert is_error(result), result
    assert result["message"] == _completed_msg(rid)
    assert _full_row(conn, rid) == before_row
    after_gl = _gl_rows(conn, rid)
    assert len(after_gl) == 2
    for row in after_gl:
        assert row["is_cancelled"] == 0
    legs = sorted((r["debit"], r["credit"]) for r in after_gl)
    assert legs == [("0.00", "120.00"), ("120.00", "0.00")]
    assert after_gl == before_gl
    assert _audit_count(conn) == before_audit


def test_edit_refund_fields_on_completed_refused(conn, env):
    rid = _make_completed(conn, env)
    cases = [
        dict(restocking_fee="5.00"),
        dict(return_type="exchange"),
        dict(original_invoice_id="x"),
    ]
    for kw in cases:
        before_row = _full_row(conn, rid)
        result = _update(conn, rid, **kw)
        assert is_error(result), (kw, result)
        assert result["message"] == _completed_msg(rid), (kw, result)
        assert _full_row(conn, rid) == before_row, kw


def test_notes_on_completed_allowed(conn, env):
    rid = _make_completed(conn, env)
    before_audit = _audit_count(conn)
    result = _update(conn, rid, notes="boxed")
    assert is_ok(result), result
    assert _full_row(conn, rid)["notes"] == "boxed"
    assert _audit_count(conn) == before_audit + 1


def test_complete_directly_refused(conn, env):
    rid = _make_pending(conn, env)
    result = _update(conn, rid, return_status="completed")
    assert is_error(result), result
    assert result["message"] == COMPLETE_DIRECT_MSG
    assert _full_row(conn, rid)["return_status"] == "pending"
    assert _gl_rows(conn, rid) == []


def test_cancelled_cannot_reopen(conn, env):
    rid = _make_pending(conn, env)
    cancelled = _update(conn, rid, return_status="cancelled")
    assert is_ok(cancelled), cancelled
    result = _update(conn, rid, return_status="pending")
    assert is_error(result), result
    assert result["message"] == _cancelled_msg(rid)
    assert _full_row(conn, rid)["return_status"] == "cancelled"


def test_pending_return_update_unchanged(conn, env):
    rid = _make_pending(conn, env)
    result = _update(conn, rid, reason="changed mind", return_status="approved")
    assert is_ok(result), result
    assert result["updated_fields"] == ["reason", "return_status"]
    stored = _full_row(conn, rid)
    assert stored["reason"] == "changed mind"
    assert stored["return_status"] == "approved"
