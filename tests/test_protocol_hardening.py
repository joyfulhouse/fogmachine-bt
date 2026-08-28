"""Wire-safety hardening of the protocol request builders.

Builders must reject anything that would corrupt a fixed-width ASCII frame
(negative numbers, field overflow, non-bool flags). App-level limits (work
3-84600 s, hours 0-23, ...) live in the coordinator, not here.
"""

from __future__ import annotations

import pytest

from custom_components.fogmachine_bt.fogmachine import protocol as p


def test_build_weekday_rejects_bool_index_and_non_bool_flag():
    with pytest.raises(ValueError):
        p.build_weekday(True, True)  # bool masquerading as day index
    with pytest.raises(ValueError):
        p.build_weekday(2, 1)  # int masquerading as flag
    with pytest.raises(ValueError):
        p.build_weekday("2", True)  # str index
    # existing semantics keep working at the bounds
    assert p.build_weekday(0, True) == b"EE03000."
    assert p.build_weekday(6, False) == b"EE03061."


def test_build_time_entry_wire_bounds():
    # full wire width is 2 digits per field -> 0..99 accepted here
    assert p.build_time_entry(99, False, 99, 99, 99, 99) == b"EE06099199999999."
    assert p.build_time_entry(0, True, 0, 0, 0, 0) == b"EE06000000000000."
    for args in (
        (-1, True, 6, 0, 22, 30),  # negative seq -> '-1' on the wire
        (100, True, 6, 0, 22, 30),  # seq overflows 2 digits
        (1, 0, 6, 0, 22, 30),  # non-bool enabled
        (1, True, -1, 0, 22, 30),  # negative hour
        (1, True, 100, 0, 22, 30),  # hour overflows 2 digits
        (1, True, 6, 0, 22, True),  # bool masquerading as minute
    ):
        with pytest.raises(ValueError):
            p.build_time_entry(*args)


def test_build_freq_entry_wire_bounds():
    # work/pause are 5-digit fields -> 0..99999 accepted here
    assert p.build_freq_entry(0, True, 0, 99999) == b"EE0700000000099999."
    assert p.build_freq_entry(99, False, 99999, 0) == b"EE0709919999900000."
    for args in (
        (-1, True, 3, 5),  # negative seq
        (100, True, 3, 5),  # seq overflows 2 digits
        (1, 0, 3, 5),  # non-bool enabled
        (1, True, -1, 5),  # negative work
        (1, True, 100000, 5),  # work overflows 5 digits
        (1, True, 3, -1),  # negative pause
        (1, True, 3, 100000),  # pause overflows 5 digits
        (1, True, True, 5),  # bool masquerading as work seconds
    ):
        with pytest.raises(ValueError):
            p.build_freq_entry(*args)


def test_build_mode_strict_and_customizable_builders():
    # build_mode was already strict via MODE_NAMES membership -- pin it down
    with pytest.raises(ValueError):
        p.build_mode("3")
    with pytest.raises(ValueError):
        p.build_mode(0)
    # new cmd 4/5 builders: single inverted-bool payload (like power)
    assert p.build_time_customizable(True) == b"EE0400."
    assert p.build_time_customizable(False) == b"EE0401."
    assert p.build_freq_customizable(True) == b"EE0500."
    assert p.build_freq_customizable(False) == b"EE0501."
    with pytest.raises(ValueError):
        p.build_time_customizable(1)  # non-bool
    with pytest.raises(ValueError):
        p.build_freq_customizable(0)  # non-bool
