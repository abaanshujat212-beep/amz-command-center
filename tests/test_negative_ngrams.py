import math

from services.rules.ngrams import (
    COVERED,
    MANUAL_REVIEW,
    NEGATIVE_PHRASE,
    PROTECTED,
    Protection,
    Thresholds,
    analyze,
    phrases,
    tokenize,
)


def _q(term, clicks=0, cost=0.0, orders=0, sales=0.0, impressions=None, campaigns=("C1",)):
    return {
        "search_term": term,
        "clicks": clicks,
        "impressions": impressions if impressions is not None else clicks * 20,
        "cost": cost,
        "orders": orders,
        "sales": sales,
        "campaign_ids": list(campaigns),
    }


# Account CVR = 10 orders / 200 clicks = 5%; 60 clicks gives exp(-3) ~ 0.0498.
BASE = [_q("hook and loop tape", clicks=100, cost=60, orders=10, sales=300)]


def _by_ngram(findings):
    return {f.ngram: f for f in findings}


def test_tokenization_handles_case_punctuation_accents_and_apostrophes():
    assert tokenize("  Men's  HOOK-and-loop, Tape!! ") == ("mens", "hook", "and", "loop", "tape")
    assert tokenize("Résumé  holder") == ("resume", "holder")
    assert tokenize("---") == ()
    assert phrases(("a", "b", "a", "b")) == {"a", "b", "a b", "b a", "a b a", "b a b"}


def test_phrase_metrics_aggregate_across_queries_and_count_once_per_query():
    rows = [*BASE, 
        _q("free sample tape", clicks=40, cost=20),
        _q("Free Sample, Velcro", clicks=20, cost=12),
        _q("free sample tape", clicks=0, cost=0),  # same query, another campaign day
        _q("free free strips", clicks=5, cost=2),
    ]
    f = _by_ngram(analyze(rows))["free sample"]
    assert (f.query_count, f.clicks, f.cost, f.orders) == (2, 60, 32.0, 0)
    # account CVR = 10 orders / 165 clicks across every analysed query
    assert f.chance_zero_orders == round(math.exp(-60 * 10 / 165), 6)
    assert f.decision == NEGATIVE_PHRASE and f.reasons == []
    assert [q["search_term"] for q in f.contributing_queries] == [
        "free sample tape",
        "free sample velcro",
    ]
    # "free" appears twice in one query but its clicks are counted once.
    assert _by_ngram(analyze(rows))["free"].clicks == 65


def test_converting_phrase_is_never_a_candidate():
    rows = [*BASE, _q("cheap tape roll", clicks=40, cost=30), _q("cheap tape pack", clicks=40,
                                                                   cost=30, orders=1)]
    found = _by_ngram(analyze(rows))
    assert "cheap tape" not in found
    assert found["tape roll"].decision == MANUAL_REVIEW  # single query


def test_ambiguous_and_low_volume_phrases_stay_manual():
    rows = [*BASE, 
        _q("for kids pink", clicks=30, cost=20),
        _q("for kids blue", clicks=30, cost=20),
        _q("rare widget a", clicks=8, cost=5),
        _q("rare widget b", clicks=7, cost=5),
    ]
    found = _by_ngram(analyze(rows))
    assert "single_word" in found["kids"].reasons
    assert found["kids"].decision == MANUAL_REVIEW
    assert "generic_tokens" in found["for"].reasons
    assert found["for kids"].decision == NEGATIVE_PHRASE
    rare = found["rare widget"]
    assert rare.decision == MANUAL_REVIEW
    assert {"low_volume", "low_confidence"} <= set(rare.reasons)


def test_thresholds_gate_confidence_and_no_account_conversions_means_manual():
    rows = [*BASE, _q("free sample tape", clicks=30, cost=20), _q("free sample x", clicks=30,
                                                                    cost=20)]
    strict = Thresholds(max_chance_zero_orders=0.01)
    assert _by_ngram(analyze(rows, thresholds=strict))["free sample"].decision == MANUAL_REVIEW
    no_cvr = [_q("free sample tape", clicks=30, cost=20), _q("free sample x", clicks=30, cost=20)]
    f = _by_ngram(analyze(no_cvr))["free sample"]
    assert f.chance_zero_orders is None and "low_confidence" in f.reasons


def test_protected_terms_block_overlap_in_both_directions():
    rows = [*BASE, _q("womens shoes red", clicks=30, cost=20), _q("womens shoes blue",
                                                                  clicks=30, cost=20)]
    inner = _by_ngram(analyze(rows, [Protection("p1", "Womens Shoes Sale")]))["womens shoes"]
    assert (inner.decision, inner.protection_id) == (PROTECTED, "p1")
    outer = _by_ngram(analyze(rows, [Protection("p2", "shoes")]))["womens shoes"]
    assert outer.decision == PROTECTED
    unrelated = _by_ngram(analyze(rows, [Protection("p3", "shoe")]))["womens shoes"]
    assert unrelated.decision == NEGATIVE_PHRASE


def test_longer_phrases_covered_by_a_shorter_negative_and_output_is_reproducible():
    rows = [*BASE, _q("free sample tape", clicks=40, cost=20), _q("free sample tape roll",
                                                                    clicks=40, cost=20)]
    first = analyze(rows)
    found = _by_ngram(first)
    assert found["free sample"].decision == NEGATIVE_PHRASE
    assert found["free sample tape"].decision == COVERED
    assert "covered_by:free sample" in found["free sample tape"].reasons
    assert [(f.ngram, f.decision) for f in analyze(list(reversed(rows)))] == [
        (f.ngram, f.decision) for f in first
    ]
    assert [f.n for f in first] == sorted(f.n for f in first)
