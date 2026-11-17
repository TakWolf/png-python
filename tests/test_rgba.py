from array import array

import pytest

from png import PngColorType, PngHeader, PngImage
from png._composite import _rgba_rows


@pytest.mark.parametrize('depth', [1, 2, 4, 8, 16])
def test_gray_rgba_scaling_matches_transparency_before_expansion(depth):
    maximum = (1 << depth) - 1
    target_depth = 16 if depth == 16 else 8
    target_maximum = (1 << target_depth) - 1
    image = PngImage(
        PngHeader((3, 1), depth, PngColorType.GRAYSCALE),
        [[0, 1, maximum]],
        transparent_color=(1,),
    )
    expected = [0, 0, 0, target_maximum]
    expected += [target_maximum // maximum] * 3 + [0]
    expected += [target_maximum] * 4
    if maximum == 1:
        expected[-1] = 0  # Both source samples with value one are transparent.
    assert _rgba_rows(image, image.bitmap, target_depth) == [expected]


@pytest.mark.parametrize('depth', [8, 16])
@pytest.mark.parametrize('kind', [PngColorType.GRAYSCALE_ALPHA, PngColorType.TRUECOLOR, PngColorType.TRUECOLOR_ALPHA])
def test_direct_rgba_channels_precision_and_independent_rows(depth, kind):
    maximum = (1 << depth) - 1
    if kind == PngColorType.GRAYSCALE_ALPHA:
        source = [1, 0, maximum - 1, maximum]
        expected = [1, 1, 1, 0, maximum - 1, maximum - 1, maximum - 1, maximum]
    else:
        source = [1, 2, 3, 1, 2, 4] if kind == PngColorType.TRUECOLOR else [1, 2, 3, 0, 1, 2, 4, maximum]
        expected = [1, 2, 3, 0, 1, 2, 4, maximum]
    rows = [bytearray(source)] if depth == 8 else [array('H', source)]
    image = PngImage(PngHeader((2, 1), depth, kind), rows)
    if kind == PngColorType.TRUECOLOR:
        image.transparent_color = (1, 2, 3)
    converted = _rgba_rows(image, image.bitmap, depth)
    assert converted == [expected]
    converted[0][0] = 0
    assert rows[0][0] == 1


@pytest.mark.parametrize('depth', [1, 2, 4, 8])
def test_indexed_rgba_uses_palette_alpha_and_implicit_opaque_entries(depth):
    image = PngImage(
        PngHeader((2, 1), depth, PngColorType.INDEXED_COLOR),
        [[0, 1]],
        palette=[(1, 2, 3), (4, 5, 6)],
        palette_alpha=[128],
    )
    assert _rgba_rows(image, image.bitmap, 8) == [[1, 2, 3, 128, 4, 5, 6, 255]]
