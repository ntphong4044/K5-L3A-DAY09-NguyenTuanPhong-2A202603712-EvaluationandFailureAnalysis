"""Regression test from docs/trace_case.md: seeded_regression C-014@11 (FM-05 pre_deducted).

The agent subtracts the 30.000 already refunded on O-515 before calling the host, the host
subtracts it again, so the ledger holds 90.000 instead of 120.000 while the reply says 120.000.
"""
import pytest

pytestmark = pytest.mark.student


def ctx(case):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="trace_case", inputs={}, metadata=None, expected_output=case["label"],
                            output=case["trial"], duration=0.0, _span_tree=None, attributes={}, metrics={})


def grade(shape):
    from lab9 import graders
    from lab9.trace_case import investigate

    c = ctx(investigate(shape, "C-014", 11))
    return (graders.RefundAmountCorrect().evaluate(c).value,
            graders.ReplyMatchesLedger().evaluate(c).value,
            c.output)


def test_lab9_trace_case_pre_deducted_is_caught():
    amount_ok, reply_ok, trial = grade("seeded_regression")
    assert trial["snapshot"]["refund_vnd"] == 90000
    kinds = [e["kind"] for e in trial["events"]]
    assert "proposal" in kinds          # first wrong step: self-deducted proposal before the host call
    assert amount_ok is False and reply_ok is False


def test_lab9_trace_case_fixed_passes():
    amount_ok, reply_ok, trial = grade("fixed")
    assert trial["snapshot"]["refund_vnd"] == 120000
    assert amount_ok is True and reply_ok is True
