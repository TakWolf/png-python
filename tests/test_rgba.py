from array import array

import pytest

from png import (
    PngAnimation,
    PngColorType,
    PngFrame,
    PngFrameControl,
    PngGamma,
    PngHeader,
    PngIccProfile,
    PngImage,
    PngPhysicalDimensions,
    PngSignificantBits,
    PngText,
    PngValidationError,
)
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
    assert image.to_rgba().bitmap == [expected]


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
    assert image.to_rgba().bitmap == [expected]
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
    assert image.to_rgba().bitmap == [[1, 2, 3, 128, 4, 5, 6, 255]]


def test_rgba_conversion_matches_transparency_before_16_to_8_scaling():
    image = PngImage(
        PngHeader((2, 1), 16, PngColorType.TRUECOLOR),
        [[256, 512, 768, 257, 512, 768]],
        transparent_color=(256, 512, 768),
    )
    result = image.to_rgba(bit_depth=8)
    assert result.bitmap == [[1, 2, 3, 0, 1, 2, 3, 255]]
    assert image.to_rgba().bitmap == [[256, 512, 768, 0, 257, 512, 768, 65535]]
    assert result.header.color_type == PngColorType.TRUECOLOR_ALPHA
    assert result.palette == [] and result.palette_alpha == [] and result.transparent_color is None
    assert PngImage.parse(result.dump_to_bytes()).bitmap == result.bitmap


def test_rgba_explicit_scaling_rounds_instead_of_stripping_low_bytes():
    image = PngImage(PngHeader((1, 1), 16), [[128, 129, 65407, 65535]])
    assert image.to_rgba(bit_depth=8).bitmap == [[0, 1, 255, 255]]
    image = PngImage(PngHeader((1, 1)), [[1, 2, 3, 128]])
    result = image.to_rgba(bit_depth=16)
    assert result.bitmap == [[257, 514, 771, 32896]]
    result.bitmap[0][0] = 0
    assert image.bitmap[0][0] == 1


def test_low_depth_and_indexed_conversion_to_rgba16():
    gray = PngImage(PngHeader((3, 1), 2, PngColorType.GRAYSCALE), [[0, 1, 3]], transparent_color=(1,))
    assert gray.to_rgba(bit_depth=16).bitmap == [[0, 0, 0, 65535, 21845, 21845, 21845, 0, 65535, 65535, 65535, 65535]]
    indexed = PngImage(
        PngHeader((2, 1), 1, PngColorType.INDEXED_COLOR),
        [[0, 1]],
        palette=[(1, 2, 3), (4, 5, 6)],
        palette_alpha=[128],
    )
    assert indexed.to_rgba(bit_depth=16).bitmap == [[257, 514, 771, 32896, 1028, 1285, 1542, 65535]]


def test_rgba_copy_keeps_applicable_metadata_independent():
    image = PngImage(
        PngHeader((1, 1), color_type=PngColorType.TRUECOLOR),
        [[1, 2, 3]],
        metadata=[PngGamma(45455), PngText('Comment', 'source'), PngSignificantBits((8, 8, 8))],
        ancillary_chunks=[PngPhysicalDimensions(10, 20).to_chunk()],
    )
    result = image.to_rgba()
    assert [entry.type for entry in result.metadata] == [b'gAMA']
    assert result.ancillary_chunks[0].type == b'pHYs'
    result.metadata[0].raw_gamma = 100000
    result.ancillary_chunks[0].data = bytes(9)
    result.bitmap[0][0] = 99
    assert image.metadata[0].raw_gamma == 45455
    assert image.ancillary_chunks[0].data != bytes(9)
    assert image.bitmap == [[1, 2, 3]]


def test_gray_icc_is_omitted_but_rgb_icc_is_copied(gray_icc_profile_bytes, icc_profile_bytes):
    gray = PngImage(
        PngHeader((1, 1), color_type=PngColorType.GRAYSCALE),
        [[1]],
        metadata=[PngIccProfile('Gray', gray_icc_profile_bytes)],
    )
    assert not gray.to_rgba().find_metadata(b'iCCP')
    rgb = PngImage(PngHeader((1, 1)), [[1, 2, 3, 255]], metadata=[PngIccProfile('RGB', icc_profile_bytes)])
    result = rgb.to_rgba()
    result.find_metadata(b'iCCP')[0].name = 'Changed'
    assert rgb.find_metadata(b'iCCP')[0].name == 'RGB'
    gray.metadata.clear()
    gray.ancillary_chunks.append(PngIccProfile('Gray', gray_icc_profile_bytes).to_chunk())
    assert not gray.to_rgba().ancillary_chunks


def test_apng_conversion_uses_default_poster_and_does_not_keep_animation():
    image = PngImage(
        PngHeader((1, 1)),
        [[255, 0, 0, 255]],
        animation=PngAnimation(frames=[PngFrame(PngFrameControl((1, 1)), [[0, 255, 0, 255]])]),
    )
    result = image.to_rgba()
    assert result.bitmap == [[255, 0, 0, 255]] and result.animation is None
    assert next(image.render_frames()).image.bitmap == [[0, 255, 0, 255]]
    assert image.animation is not None


@pytest.mark.parametrize('bit_depth', [True, False, 0, 9, 12, 17, 8.0, '8'])
def test_rgba_conversion_rejects_invalid_target_depth(bit_depth):
    image = PngImage(PngHeader((1, 1)), [[1, 2, 3, 4]])
    with pytest.raises(PngValidationError, match='RGBA bit depth'):
        image.to_rgba(bit_depth=bit_depth)


def test_rgba_conversion_validates_modified_source():
    image = PngImage(PngHeader((1, 1)), [[1, 2, 3, 256]])
    with pytest.raises(PngValidationError):
        image.to_rgba()
