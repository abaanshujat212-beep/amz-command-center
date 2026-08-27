import pytest

from services.copilot.voice import classify, normalize_text


def test_normalize_text_collapses_whitespace_and_case():
    assert normalize_text("  ACOS   Kya  Hai ") == "acos kya hai"


def test_voice_spend_question_routes_to_answer_tier():
    intent = classify("pichlay haftay spend aur ACOS batao")
    assert intent.kind == "answer"
    assert intent.tier == "T1"
    assert "ACOS" in intent.normalized_question
    assert intent.requires_confirmation is False


def test_voice_opportunity_question_maps_to_product_sqp_context():
    intent = classify("best opportunity aur mauqa batao")
    assert intent.kind == "answer"
    assert "SQP" in intent.normalized_question


def test_voice_write_like_command_becomes_confirmed_proposal_not_apply():
    intent = classify("top campaign ka budget increase kar do")
    assert intent.kind == "proposal"
    assert intent.tier == "T2"
    assert intent.requires_confirmation is True


def test_voice_empty_text_is_rejected():
    with pytest.raises(ValueError):
        classify("   ")
