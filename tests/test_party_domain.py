from services.party.repository import PartyInput, normalize


def test_party_input_is_multi_role_neutral():
    value = PartyInput("Acme Logistics Ltd.")
    assert value.party_kind == "organization"
    assert normalize(value.display_name) == "acme logistics ltd"


def test_normalize_supports_duplicate_detection():
    assert normalize(" ACME—Logistics, Ltd ") == normalize("acme logistics ltd")
