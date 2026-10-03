"""Store credit behaviour, read back from the database.

Actions tested:
  - retail-issue-store-credit
  - retail-redeem-store-credit
  - retail-check-store-credit-balance

Every balance is compared as an exact string. Refusals are pinned to their
reason and to the table and audit rows they must not have written.
"""
import json
from decimal import Decimal

from retail_helpers import call_action, ns, is_error, is_ok, load_db_query, seed_customer

mod = load_db_query()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _issue(conn, env, amount, source="return", customer_id=None, company_id=None):
    return call_action(mod.retail_issue_store_credit, conn, ns(
        company_id=company_id or env["company_id"],
        customer_id=customer_id or env["customer_id"],
        amount=amount,
        source=source,
        reference_id=None,
        expiration_date=None,
    ))


def _redeem(conn, store_credit_id, amount):
    return call_action(mod.retail_redeem_store_credit, conn, ns(
        store_credit_id=store_credit_id,
        amount=amount,
    ))


def _balance(conn, customer_id):
    return call_action(mod.retail_check_store_credit_balance, conn, ns(
        customer_id=customer_id,
    ))


def _credit(conn, store_credit_id):
    return conn.execute(
        "SELECT customer_id, company_id, original_amount, remaining_balance, "
        "status, source FROM retailclaw_store_credit WHERE id = ?",
        (store_credit_id,),
    ).fetchone()


def _credit_count(conn):
    return conn.execute("SELECT COUNT(*) FROM retailclaw_store_credit").fetchone()[0]


def _audit(conn, action):
    rows = conn.execute(
        "SELECT skill, entity_type, entity_id, new_values FROM audit_log "
        "WHERE action = ?",
        (action,),
    ).fetchall()
    return [(r["skill"], r["entity_type"], r["entity_id"], json.loads(r["new_values"]))
            for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# retail-issue-store-credit
# ─────────────────────────────────────────────────────────────────────────────

class TestIssueStoreCredit:
    def test_issue_writes_active_credit_with_full_balance(self, conn, env):
        r = _issue(conn, env, "250.00", source="return")
        assert is_ok(r), r
        sc_id = r["store_credit_id"]
        assert r["amount"] == "250.00"
        assert r["credit_status"] == "active"

        row = _credit(conn, sc_id)
        assert row["customer_id"] == env["customer_id"]
        assert row["company_id"] == env["company_id"]
        assert row["original_amount"] == "250.00"
        assert row["remaining_balance"] == "250.00"
        assert row["status"] == "active"
        assert row["source"] == "return"
        assert _credit_count(conn) == 1

        assert _audit(conn, "retail-issue-store-credit") == [(
            "retailclaw", "retailclaw_store_credit", sc_id,
            {"customer_id": env["customer_id"], "amount": "250.00"},
        )]

    def test_issue_without_source_defaults_to_adjustment(self, conn, env):
        r = _issue(conn, env, "12.34", source=None)
        assert is_ok(r), r
        row = _credit(conn, r["store_credit_id"])
        assert (row["source"], row["original_amount"], row["remaining_balance"]) == (
            "adjustment", "12.34", "12.34")

    def test_issue_refuses_zero_amount(self, conn, env):
        r = _issue(conn, env, "0")
        assert is_error(r), r
        assert r["message"] == "--amount must be greater than zero"
        assert _credit_count(conn) == 0
        assert _audit(conn, "retail-issue-store-credit") == []

    def test_issue_refuses_negative_amount(self, conn, env):
        r = _issue(conn, env, "-50.00")
        assert is_error(r), r
        assert r["message"] == "--amount must be greater than zero"
        assert _credit_count(conn) == 0
        assert _audit(conn, "retail-issue-store-credit") == []

    def test_issue_refuses_invalid_source(self, conn, env):
        r = _issue(conn, env, "10.00", source="bonus")
        assert is_error(r), r
        assert r["message"] == (
            "Invalid source: bonus. Must be one of: return, promotion, adjustment, gift")
        assert _credit_count(conn) == 0

    def test_issue_refuses_unknown_company(self, conn, env):
        r = _issue(conn, env, "10.00", company_id="no-such-company")
        assert is_error(r), r
        assert r["message"] == "Company no-such-company not found"
        assert _credit_count(conn) == 0


# ─────────────────────────────────────────────────────────────────────────────
# retail-redeem-store-credit
# ─────────────────────────────────────────────────────────────────────────────

class TestRedeemStoreCredit:
    def test_partial_redemption_leaves_exact_balance(self, conn, env):
        sc_id = _issue(conn, env, "100.00")["store_credit_id"]

        r = _redeem(conn, sc_id, "30.25")
        assert is_ok(r), r
        assert r["redeemed_amount"] == "30.25"
        assert r["remaining_balance"] == "69.75"
        assert r["document_status"] == "active"

        row = _credit(conn, sc_id)
        assert row["original_amount"] == "100.00"
        assert row["remaining_balance"] == "69.75"
        assert row["status"] == "active"

        assert _audit(conn, "retail-redeem-store-credit") == [(
            "retailclaw", "retailclaw_store_credit", sc_id,
            {"redeemed": "30.25", "remaining": "69.75"},
        )]

    def test_redeeming_the_rest_marks_credit_redeemed(self, conn, env):
        sc_id = _issue(conn, env, "100.00")["store_credit_id"]

        first = _redeem(conn, sc_id, "40.00")
        assert is_ok(first), first
        assert _credit(conn, sc_id)["remaining_balance"] == "60.00"
        assert _credit(conn, sc_id)["status"] == "active"

        last = _redeem(conn, sc_id, "60.00")
        assert is_ok(last), last
        assert last["remaining_balance"] == "0.00"
        assert last["document_status"] == "redeemed"

        row = _credit(conn, sc_id)
        assert row["original_amount"] == "100.00"
        assert row["remaining_balance"] == "0.00"
        assert row["status"] == "redeemed"
        assert len(_audit(conn, "retail-redeem-store-credit")) == 2

    def test_over_redemption_refused_and_balance_untouched(self, conn, env):
        sc_id = _issue(conn, env, "50.00")["store_credit_id"]

        r = _redeem(conn, sc_id, "50.01")
        assert is_error(r), r
        assert r["message"] == "Redemption amount 50.01 exceeds remaining balance 50.00"

        row = _credit(conn, sc_id)
        assert (row["remaining_balance"], row["status"]) == ("50.00", "active")
        assert _audit(conn, "retail-redeem-store-credit") == []

    def test_fully_redeemed_credit_refuses_further_redemption(self, conn, env):
        sc_id = _issue(conn, env, "20.00")["store_credit_id"]
        assert is_ok(_redeem(conn, sc_id, "20.00"))

        r = _redeem(conn, sc_id, "1.00")
        assert is_error(r), r
        assert r["message"] == "Store credit is redeemed"

        row = _credit(conn, sc_id)
        assert (row["remaining_balance"], row["status"]) == ("0.00", "redeemed")
        assert len(_audit(conn, "retail-redeem-store-credit")) == 1

    def test_expired_credit_refuses_redemption(self, conn, env):
        sc_id = _issue(conn, env, "75.00")["store_credit_id"]
        conn.execute("UPDATE retailclaw_store_credit SET status = 'expired' WHERE id = ?",
                     (sc_id,))
        conn.commit()

        r = _redeem(conn, sc_id, "5.00")
        assert is_error(r), r
        assert r["message"] == "Store credit is expired"

        row = _credit(conn, sc_id)
        assert (row["remaining_balance"], row["status"]) == ("75.00", "expired")
        assert _audit(conn, "retail-redeem-store-credit") == []

    def test_zero_redemption_refused(self, conn, env):
        sc_id = _issue(conn, env, "100.00")["store_credit_id"]

        r = _redeem(conn, sc_id, "0")
        assert is_error(r), r
        assert r["message"] == "--amount must be greater than zero"

        row = _credit(conn, sc_id)
        assert (row["remaining_balance"], row["status"]) == ("100.00", "active")
        assert _audit(conn, "retail-redeem-store-credit") == []

    def test_negative_redemption_refused_and_balance_not_inflated(self, conn, env):
        sc_id = _issue(conn, env, "100.00")["store_credit_id"]

        r = _redeem(conn, sc_id, "-50.00")
        assert is_error(r), r
        assert r["message"] == "--amount must be greater than zero"

        row = _credit(conn, sc_id)
        assert (row["original_amount"], row["remaining_balance"], row["status"]) == (
            "100.00", "100.00", "active")
        assert _audit(conn, "retail-redeem-store-credit") == []

    def test_unknown_credit_refused(self, conn, env):
        r = _redeem(conn, "no-such-credit", "5.00")
        assert is_error(r), r
        assert r["message"] == "Store credit no-such-credit not found"
        assert _audit(conn, "retail-redeem-store-credit") == []


# ─────────────────────────────────────────────────────────────────────────────
# retail-check-store-credit-balance
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckStoreCreditBalance:
    def test_balance_sums_only_active_credits_of_the_customer(self, conn, env):
        first = _issue(conn, env, "100.00")["store_credit_id"]
        second = _issue(conn, env, "25.50", source="gift")["store_credit_id"]
        spent = _issue(conn, env, "40.00")["store_credit_id"]
        assert is_ok(_redeem(conn, first, "10.00"))
        assert is_ok(_redeem(conn, spent, "40.00"))

        other = seed_customer(conn, env["company_id"], "Other Customer")
        assert is_ok(_issue(conn, env, "999.00", customer_id=other))

        r = _balance(conn, env["customer_id"])
        assert is_ok(r), r
        assert r["customer_id"] == env["customer_id"]
        assert r["active_credits"] == 2
        assert r["total_balance"] == "115.50"
        assert {(c["id"], c["remaining_balance"], c["status"]) for c in r["credits"]} == {
            (first, "90.00", "active"),
            (second, "25.50", "active"),
        }

        rows = conn.execute(
            "SELECT remaining_balance FROM retailclaw_store_credit "
            "WHERE customer_id = ? AND status = 'active'",
            (env["customer_id"],),
        ).fetchall()
        assert sum((Decimal(x["remaining_balance"]) for x in rows), Decimal("0")) == Decimal("115.50")
        assert _credit(conn, spent)["status"] == "redeemed"

        assert _balance(conn, other)["total_balance"] == "999.00"

    def test_customer_without_credit_has_zero_balance(self, conn, env):
        r = _balance(conn, env["customer_id"])
        assert is_ok(r), r
        assert r["active_credits"] == 0
        assert r["total_balance"] == "0.00"
        assert r["credits"] == []

    def test_balance_requires_customer_id(self, conn, env):
        r = _balance(conn, None)
        assert is_error(r), r
        assert r["message"] == "--customer-id is required"
