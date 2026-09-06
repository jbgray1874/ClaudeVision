"""A customer name that picked up the job number still matches its logo.

7332-01's quote read "Harrods 7332-01" with no logo. _normalise_key keeps digits, so the
job-numbered name keyed to 'harrods733201' and no saved 'Harrods' logo file could ever match —
and the same string printed as the heading. The name is cleaned to the customer alone before the
logo lookup and the heading; the job/drawing reference already appears on its own line.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import client_quote_html as q  # noqa: E402


def test_a_job_code_is_stripped_from_the_customer_name():
    assert q._clean_customer_name("Harrods 7332-01") == "Harrods"
    assert q._clean_customer_name("Boots 11350") == "Boots"
    assert q._clean_customer_name("Milwaukee 1282-01") == "Milwaukee"


def test_the_cleaned_name_keys_to_the_logo_file():
    # the whole point: the key must match a saved 'Harrods' logo, not 'harrods733201'
    assert q._normalise_key(q._clean_customer_name("Harrods 7332-01")) == "harrods"
    assert q._normalise_key(q._clean_customer_name("Harrods 7332-01")) == q._normalise_key("Harrods")


def test_a_digit_bearing_brand_is_left_alone():
    for brand in ("3M", "7-Eleven", "M&S", "Harrods"):
        assert q._clean_customer_name(brand) == brand


def test_a_name_that_is_only_a_code_is_not_emptied():
    # never return "" — fall back to the original string rather than a blank customer block
    assert q._clean_customer_name("7332-01") == "7332-01"
