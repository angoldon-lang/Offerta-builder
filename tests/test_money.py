from decimal import Decimal

import pytest

from offerta_builder.money import (
    close_enough, format_eur, format_number, format_percent, parse_decimal, q2, relative_gap,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.234,56", Decimal("1234.56")),
        ("1,234.56", Decimal("1234.56")),
        ("9.749,30 €", Decimal("9749.30")),
        ("66,02%", Decimal("66.02")),
        ("(1.200,00)", Decimal("-1200.00")),
        ("28692.00", Decimal("28692.00")),
        ("1.234", Decimal("1234")),
        ("12,5", Decimal("12.5")),
        (1500, Decimal("1500")),
        (Decimal("3.3"), Decimal("3.3")),
    ],
)
def test_parse_decimal_formati_it_en(raw, expected):
    assert parse_decimal(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "n/d", "-", True])
def test_parse_decimal_valori_non_numerici(raw):
    assert parse_decimal(raw) is None


def test_formattazione_italiana():
    assert format_eur("12186.93") == "12.186,93 €"
    assert format_eur("-1200") == "-1.200,00 €"
    assert format_percent("66.0234") == "66,02%"
    assert format_number(1500) == "1.500"


def test_arrotondamento_half_up():
    assert q2(Decimal("1.005")) == Decimal("1.01")
    assert q2(Decimal("2.344")) == Decimal("2.34")


def test_punto_su_tre_cifre_letto_come_migliaia():
    """Convenzione IT: '1.005' è millecinque, non uno virgola zerozerocinque."""
    assert parse_decimal("1.005") == Decimal("1005")
    assert parse_decimal("1.5") == Decimal("1.5")
    assert parse_decimal("28692.00") == Decimal("28692.00")


def test_confronti_tolleranti():
    assert close_enough(Decimal("10.00"), Decimal("10.01"))
    assert not close_enough(Decimal("10.00"), Decimal("10.05"))
    assert relative_gap(Decimal("100"), Decimal("102")) == Decimal("2") / Decimal("102")
