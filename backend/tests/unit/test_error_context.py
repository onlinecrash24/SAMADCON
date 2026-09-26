"""An error carries in its context every value its English sentence names.

The interface translates by code and fills placeholders from the context. A
value only in the server's sentence — "Port must be between 1 and 65535",
"The logon name must not exceed 20 characters" — was lost in German, where the
translation could say neither which field nor which limit.
"""

from __future__ import annotations

import pytest

from samadcon.ad import dnsrecords
from samadcon.core.errors import InvalidRequest


def refused(call, *args, **kwargs) -> InvalidRequest:
    with pytest.raises(InvalidRequest) as caught:
        call(*args, **kwargs)
    return caught.value


def test_a_dns_field_is_named_by_a_stable_key():
    error = refused(dnsrecords.normalise_name, "", what="Mail server")
    assert (error.code, error.context["reason"]) == ("missing_dns_name", "mail_server")


def test_a_number_says_which_field_and_which_range():
    error = refused(dnsrecords.validate_data, "SRV", {"priority": 1, "weight": 1, "port": 0, "target": "x"})
    assert error.code == "number_out_of_range"
    assert error.context == {"value": 0, "reason": "port", "minimum": 1, "maximum": 65535}

    error = refused(dnsrecords.validate_data, "MX", {"preference": "high", "exchange": "mx"})
    assert (error.code, error.context["reason"]) == ("invalid_number", "preference")


def test_a_text_record_says_its_limit():
    error = refused(dnsrecords.validate_data, "TXT", {"strings": ["x" * 300]})
    assert error.context["limit"] == dnsrecords.MAX_TXT_STRING


def test_an_unsupported_record_type_is_named():
    error = refused(dnsrecords.validate_data, "LOC", {})
    assert error.context["type"] == "LOC"
