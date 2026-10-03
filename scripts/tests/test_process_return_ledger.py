"""Ledger posting for retail_process_return.

A completed return that moves money posts its refund ledger in the same
transaction, or the completion is refused and rolled back.
"""
import json

import pytest

from erpclaw_lib.query import Q, P, Table
from retail_helpers import call_action, ns, is_error, is_ok, load_db_query

mod = load_db_query()


def _return(conn, env, fee=None):
    ra = call_action(mod.retail_add_return_authorization, conn, ns(
        company_id=env["company_id"],
        customer_id=env["customer_id"],
        customer_name="Ledger Customer",
        return_date="2026-03-10",
        reason="Ledger test",
        return_type="refund",
        original_invoice_id=None,
        notes=None,
    ))
    assert is_ok(ra), ra
    rid = ra["id"]
    if fee is not None:
        upd = call_action(mod.retail_update_return_authorization, conn, ns(
            return_id=rid,
            customer_name=None,
            reason=None,
            original_invoice_id=None,
            notes=None,
            return_type=None,
            return_status=None,
            restocking_fee=fee,
        ))
        assert is_ok(upd), upd
    item = call_action(mod.retail_add_return_item, conn, ns(
        return_id=rid,
        item_id=env["item1"],
        item_name="Widget A",
        qty="2",
        rate="30.00",
        reason=None,
        item_condition="good",
        disposition="restock",
    ))
    assert is_ok(item), item
    return rid


def _process(conn, rid, **kw):
    params = dict(
        return_id=rid,
        return_status="completed",
        sales_returns_account_id=None,
        cash_account_id=None,
        inventory_account_id=None,
        cogs_account_id=None,
        cost_center_id=None,
        restock_cost=None,
    )
    params.update(kw)
    return call_action(mod.retail_process_return, conn, ns(**params))


def _gl_rows(conn, rid):
    t = Table("gl_entry")
    q = Q.from_(t).select(t.star).where(t.voucher_id == P())
    return [dict(r) for r in conn.execute(q.get_sql(), (rid,)).fetchall()]


def _legs(conn, rid):
    return sorted(
        (r["entry_set"], r["account_id"], r["debit"], r["credit"],
         r["cost_center_id"], r["party_id"])
        for r in _gl_rows(conn, rid)
    )


def _row(conn, rid):
    t = Table("retailclaw_return_authorization")
    q = Q.from_(t).select(t.return_status, t.gl_entry_ids).where(t.id == P())
    return dict(conn.execute(q.get_sql(), (rid,)).fetchone())


def _full(env):
    return dict(
        sales_returns_account_id=env["sales_returns_acct"],
        cash_account_id=env["cash_acct"],
        cost_center_id=env["cc"],
    )


class TestRefundPostsTwoLegs:
    def test_refund_posts_two_legs(self, conn, env):
        rid = _return(conn, env)
        result = _process(conn, rid, **_full(env))
        assert is_ok(result), result
        assert "gl_warnings" not in result
        assert result["refund_amount"] == "60.00"
        assert _legs(conn, rid) == sorted([
            ("primary", env["sales_returns_acct"], "60.00", "0.00", env["cc"], None),
            ("primary", env["cash_acct"], "0.00", "60.00", None, env["customer_id"]),
        ])
        rows = _gl_rows(conn, rid)
        assert len(rows) == 2
        for r in rows:
            assert r["voucher_type"] == "journal_entry"
            assert r["posting_date"] == "2026-03-10"
        cash_rows = [r for r in rows if r["account_id"] == env["cash_acct"]]
        assert len(cash_rows) == 1
        assert cash_rows[0]["party_type"] == "customer"
        assert len(result["gl_entry_ids"]) == 2
        assert set(result["gl_entry_ids"]) == {r["id"] for r in rows}
        stored = _row(conn, rid)
        assert stored["return_status"] == "completed"
        assert json.loads(stored["gl_entry_ids"]) == result["gl_entry_ids"]
        assert set(json.loads(stored["gl_entry_ids"])) == {r["id"] for r in rows}


class TestRefundWithoutAccounts:
    @pytest.mark.parametrize("kw", [
        {},
        {"sales": True},
        {"cash": True},
    ])
    def test_refund_without_accounts_is_refused(self, conn, env, kw):
        rid = _return(conn, env)
        extra = {}
        if kw.get("sales"):
            extra["sales_returns_account_id"] = env["sales_returns_acct"]
            extra["cost_center_id"] = env["cc"]
        if kw.get("cash"):
            extra["cash_account_id"] = env["cash_acct"]
            extra["cost_center_id"] = env["cc"]
        result = _process(conn, rid, **extra)
        assert is_error(result), result
        assert "--sales-returns-account-id" in result["message"]
        assert "--cash-account-id" in result["message"]
        stored = _row(conn, rid)
        assert stored["return_status"] == "pending"
        assert stored["gl_entry_ids"] is None
        assert _legs(conn, rid) == []
        received = _process(conn, rid, return_status="received")
        assert is_ok(received), received
        assert _legs(conn, rid) == []
        assert _row(conn, rid)["return_status"] == "received"


class TestPostingFailureRollsBack:
    def test_posting_failure_rolls_back(self, conn, env):
        rid = _return(conn, env)
        result = _process(
            conn, rid,
            sales_returns_account_id=env["sales_returns_acct"],
            cash_account_id=env["cash_acct"],
            cost_center_id=None,
        )
        assert is_error(result), result
        assert result["message"].startswith("GL posting failed, return rolled back:")
        assert "GL Validation Step 6 Failed" in result["message"]
        stored = _row(conn, rid)
        assert stored["return_status"] == "pending"
        assert stored["gl_entry_ids"] is None
        assert _legs(conn, rid) == []
        fixed = _process(conn, rid, **_full(env))
        assert is_ok(fixed), fixed
        assert _legs(conn, rid) == sorted([
            ("primary", env["sales_returns_acct"], "60.00", "0.00", env["cc"], None),
            ("primary", env["cash_acct"], "0.00", "60.00", None, env["customer_id"]),
        ])


class TestZeroRefund:
    def test_zero_refund_completes_without_posting(self, conn, env):
        rid = _return(conn, env, fee="60.00")
        result = _process(conn, rid)
        assert is_ok(result), result
        assert result["refund_amount"] == "0.00"
        assert _legs(conn, rid) == []
        assert "gl_entry_ids" not in result
        stored = _row(conn, rid)
        assert stored["return_status"] == "completed"
        assert stored["gl_entry_ids"] is None


class TestRestockFlags:
    @pytest.mark.parametrize("which", ["inventory", "cogs", "cost", "all"])
    def test_restock_flags_are_refused(self, conn, env, which):
        rid = _return(conn, env)
        extra = _full(env)
        if which in ("inventory", "all"):
            extra["inventory_account_id"] = env["inventory_acct"]
        if which in ("cogs", "all"):
            extra["cogs_account_id"] = env["cogs_acct"]
        if which in ("cost", "all"):
            extra["restock_cost"] = "36.00"
        result = _process(conn, rid, **extra)
        assert is_error(result), result
        assert "restock posting is not supported" in result["message"]
        stored = _row(conn, rid)
        assert stored["return_status"] == "pending"
        assert _legs(conn, rid) == []

    def test_restock_flags_refused_on_zero_refund(self, conn, env):
        rid = _return(conn, env, fee="60.00")
        result = _process(
            conn, rid,
            **_full(env),
            inventory_account_id=env["inventory_acct"],
            cogs_account_id=env["cogs_acct"],
            restock_cost="36.00",
        )
        assert is_error(result), result
        assert "restock posting is not supported" in result["message"]
        stored = _row(conn, rid)
        assert stored["return_status"] == "pending"
        assert _legs(conn, rid) == []


class TestRestockingFee:
    def test_restocking_fee_reduces_refund_legs(self, conn, env):
        rid = _return(conn, env, fee="5.00")
        result = _process(conn, rid, **_full(env))
        assert is_ok(result), result
        assert result["refund_amount"] == "55.00"
        assert _legs(conn, rid) == sorted([
            ("primary", env["sales_returns_acct"], "55.00", "0.00", env["cc"], None),
            ("primary", env["cash_acct"], "0.00", "55.00", None, env["customer_id"]),
        ])


class TestNoGlLibrary:
    def test_no_gl_library_is_refused(self, conn, env, monkeypatch):
        monkeypatch.setitem(mod.retail_process_return.__globals__, "HAS_GL", False)
        rid = _return(conn, env)
        result = _process(conn, rid, **_full(env))
        assert is_error(result), result
        assert "GL posting is not available; a return with a refund cannot be completed" in result["message"]
        stored = _row(conn, rid)
        assert stored["return_status"] == "pending"
        assert _legs(conn, rid) == []
