"""Behaviour tests for retail-redeem-gift-card.

Pins, reading the gift card row back from retailclaw_gift_card:
  - a partial redemption leaves the exact remaining balance and keeps the card active;
  - redeeming the rest leaves "0.00" and marks the card redeemed, after which a
    further redemption is refused;
  - redemption by gift card id reaches the same row as redemption by card number;
  - refusal of an amount that is not greater than zero (zero, negative, and a
    sub-cent amount that rounds to 0.00), of an amount above the balance, of a
    missing amount, and of an unknown card, each with its reason and with the
    balance, the status and the audit_log row count unchanged.

Deliberately not pinned: a non-numeric --amount (the handler raises rather than
returning an error), and the contents of the audit_log row.
"""
from retail_helpers import call_action, ns, is_error, is_ok, load_db_query

mod = load_db_query()

MSG_NOT_POSITIVE = "--amount must be greater than zero"


def _add_card(conn, env, card_number, initial_balance):
    r = call_action(mod.retail_add_gift_card, conn, ns(
        company_id=env["company_id"],
        card_number=card_number,
        initial_balance=initial_balance,
        currency=None,
        purchaser_name=None,
        recipient_name=None,
        recipient_email=None,
        issue_date="2026-03-01",
        expiration_date=None,
    ))
    assert is_ok(r), r
    return r["id"]


def _redeem(conn, amount, card_number=None, gift_card_id=None):
    return call_action(mod.retail_redeem_gift_card, conn, ns(
        card_number=card_number,
        gift_card_id=gift_card_id,
        amount=amount,
    ))


def _card(conn, gc_id):
    row = conn.execute(
        "SELECT initial_balance, current_balance, card_status "
        "FROM retailclaw_gift_card WHERE id = ?",
        (gc_id,),
    ).fetchone()
    return (row["initial_balance"], row["current_balance"], row["card_status"])


def _audit_count(conn):
    return conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]


class TestRedeemGiftCardBalance:

    def test_partial_redemption_leaves_exact_balance(self, conn, env):
        gc_id = _add_card(conn, env, "GC-DEPTH-001", "100.00")
        audit_before = _audit_count(conn)

        r = _redeem(conn, "30.25", card_number="GC-DEPTH-001")
        assert is_ok(r), r
        assert r["amount_redeemed"] == "30.25"
        assert r["current_balance"] == "69.75"
        assert r["card_status"] == "active"
        assert _card(conn, gc_id) == ("100.00", "69.75", "active")
        assert _audit_count(conn) == audit_before + 1

    def test_redeeming_the_rest_marks_card_redeemed(self, conn, env):
        gc_id = _add_card(conn, env, "GC-DEPTH-002", "100.00")
        assert is_ok(_redeem(conn, "30.25", card_number="GC-DEPTH-002"))

        r = _redeem(conn, "69.75", card_number="GC-DEPTH-002")
        assert is_ok(r), r
        assert r["current_balance"] == "0.00"
        assert r["card_status"] == "redeemed"
        assert _card(conn, gc_id) == ("100.00", "0.00", "redeemed")

        audit_before = _audit_count(conn)
        again = _redeem(conn, "1.00", card_number="GC-DEPTH-002")
        assert is_error(again)
        assert again["message"] == "Gift card is redeemed. Cannot redeem."
        assert _card(conn, gc_id) == ("100.00", "0.00", "redeemed")
        assert _audit_count(conn) == audit_before

    def test_redeem_by_gift_card_id(self, conn, env):
        gc_id = _add_card(conn, env, "GC-DEPTH-003", "50.00")
        r = _redeem(conn, "12.34", gift_card_id=gc_id)
        assert is_ok(r), r
        assert r["card_number"] == "GC-DEPTH-003"
        assert _card(conn, gc_id) == ("50.00", "37.66", "active")


class TestRedeemGiftCardRefusals:

    @staticmethod
    def _assert_refused(conn, gc_id, audit_before, r, message):
        assert is_error(r), r
        assert r["message"] == message
        assert _card(conn, gc_id) == ("100.00", "100.00", "active")
        assert _audit_count(conn) == audit_before

    def test_refuses_zero_amount(self, conn, env):
        gc_id = _add_card(conn, env, "GC-ZERO-001", "100.00")
        before = _audit_count(conn)
        self._assert_refused(
            conn, gc_id, before, _redeem(conn, "0", card_number="GC-ZERO-001"),
            MSG_NOT_POSITIVE)

    def test_refuses_negative_amount(self, conn, env):
        # Without the guard this passes the balance check and raises the
        # balance to 125.00, above the card's initial balance.
        gc_id = _add_card(conn, env, "GC-NEG-001", "100.00")
        before = _audit_count(conn)
        self._assert_refused(
            conn, gc_id, before, _redeem(conn, "-25.00", card_number="GC-NEG-001"),
            MSG_NOT_POSITIVE)

    def test_refuses_amount_that_rounds_to_zero(self, conn, env):
        gc_id = _add_card(conn, env, "GC-SUBCENT-001", "100.00")
        before = _audit_count(conn)
        self._assert_refused(
            conn, gc_id, before, _redeem(conn, "0.004", card_number="GC-SUBCENT-001"),
            MSG_NOT_POSITIVE)

    def test_refuses_amount_above_balance(self, conn, env):
        gc_id = _add_card(conn, env, "GC-OVER-001", "100.00")
        before = _audit_count(conn)
        self._assert_refused(
            conn, gc_id, before, _redeem(conn, "100.01", card_number="GC-OVER-001"),
            "Insufficient balance. Current: 100.00, requested: 100.01")

    def test_refuses_missing_amount(self, conn, env):
        gc_id = _add_card(conn, env, "GC-NOAMT-002", "100.00")
        before = _audit_count(conn)
        self._assert_refused(
            conn, gc_id, before, _redeem(conn, None, card_number="GC-NOAMT-002"),
            "--amount is required")

    def test_refuses_unknown_card(self, conn, env):
        gc_id = _add_card(conn, env, "GC-KNOWN-001", "100.00")
        before = _audit_count(conn)
        self._assert_refused(
            conn, gc_id, before, _redeem(conn, "10.00", card_number="GC-NO-SUCH-CARD"),
            "Gift card not found")
