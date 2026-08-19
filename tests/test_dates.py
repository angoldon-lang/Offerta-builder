from datetime import date

import pytest

from offerta_builder.dates import add_years, parse_date_strict, parse_period, to_it, to_iso


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("31/07/2026", date(2026, 7, 31)),
        ("2026-07-31", date(2026, 7, 31)),
        ("31 Dec 2026", date(2026, 12, 31)),
        ("1 gennaio 2027", date(2027, 1, 1)),
        ("19/07/26", date(2026, 7, 19)),
    ],
)
def test_date_valide(raw, expected):
    assert parse_date_strict(raw)[0] == expected


def test_data_inesistente_viene_distinta_dal_formato():
    assert parse_date_strict("31-9-2026") == (None, "inesistente")
    assert parse_date_strict("30/02/2026") == (None, "inesistente")
    assert parse_date_strict("prossimamente") == (None, "formato")
    assert parse_date_strict("") == (None, "vuota")


def test_periodo_con_due_estremi():
    assert parse_period("31 Dec 2026 - 30 Dec 2027") == (date(2026, 12, 31), date(2027, 12, 30))
    assert parse_period("01/01/2027 al 31/12/2027") == (date(2027, 1, 1), date(2027, 12, 31))


def test_conversioni():
    assert to_it("2026-07-31") == "31/07/2026"
    assert to_iso("31/07/2026") == "2026-07-31"
    assert to_it("31-9-2026") == ""
    assert add_years(date(2024, 2, 29), 1) == date(2025, 2, 28)
