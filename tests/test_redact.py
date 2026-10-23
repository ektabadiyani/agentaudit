from agentaudit.redact import Redactor, luhn_valid


def test_luhn():
    assert luhn_valid("4111111111111111")
    assert not luhn_valid("4111111111111112")


def test_redacts_common_identifiers_and_counts_them():
    r = Redactor()
    text = ("I'm jane.doe+billing@harbor.example, call me on +1 (415) 555-0134. "
            "Card 4111 1111 1111 1111, SSN 123-45-6789, logged in from 192.168.10.4.")
    out = r.redact(text)
    for secret in ["jane.doe", "555-0134", "4111", "123-45-6789", "192.168"]:
        assert secret not in out
    assert out.count("[EMAIL]") == 1 and "[PHONE]" in out and "[CARD]" in out and "[SSN]" in out and "[IP]" in out
    assert r.counts == {"EMAIL": 1, "PHONE": 1, "CARD": 1, "SSN": 1, "IP": 1}


def test_leaves_prices_dates_and_short_numbers_alone():
    text = "Team is $12 per member; we added 3 seats on 2026-11-02 and invoice 48213 is due."
    assert Redactor().redact(text) == text


def test_random_long_number_that_fails_luhn_is_not_called_a_card():
    assert "[CARD]" not in Redactor().redact("Order 1234567890123 shipped")


def test_custom_patterns_run_first():
    r = Redactor(extra={"account_id": r"\bACC-\d{6}\b"})
    assert r.redact("Account ACC-123456 is locked") == "Account [ACCOUNT_ID] is locked"
