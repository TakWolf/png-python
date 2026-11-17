"""Paeth's normative prediction, independent of the inlined difference form."""

from itertools import product

import pytest

from png._pixels import _filter, _filter_and_score, _unfilter


@pytest.mark.parametrize('stride', [1, 2, 3, 4, 6, 8])
def test_paeth_boundaries_ties_wrap_and_scoring(stride):
    for left, above, upper_left in product((0, 1, 127, 128, 254, 255), repeat=3):
        prediction = left + above - upper_left
        # min keeps the first candidate on ties: left, above, upper-left.
        predictor = min((left, above, upper_left), key=lambda value: abs(prediction - value))
        row = bytes([left] * stride + [128] * stride)
        previous = bytes([upper_left] * stride + [above] * stride)
        expected = bytes([(left - upper_left) & 255] * stride + [(128 - predictor) & 255] * stride)
        assert _filter(4, row, previous, stride) == expected
        assert _unfilter(4, expected, previous, stride) == row
        score = sum(min(value, 256 - value) for value in expected)
        for minimum in (0, score // 2, score, score + 1):
            trial = bytearray(b'\xa5' * len(row))
            actual = _filter_and_score(4, row, previous, stride, trial, minimum)
            if score > minimum:
                assert actual > minimum
            else:
                assert actual == score
                assert trial == expected
        # A one-pixel row has only the Up-equivalent prefix.
        assert _filter(4, row[:stride], previous[:stride], stride) == expected[:stride]
        assert _unfilter(4, expected[:stride], previous[:stride], stride) == row[:stride]
