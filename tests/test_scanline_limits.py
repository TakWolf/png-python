import zlib
from io import BytesIO

import pytest

from png import (
    PngAnimation,
    PngColorType,
    PngDocument,
    PngFilterType,
    PngFrame,
    PngFrameControl,
    PngHeader,
    PngImage,
    PngInterlaceMethod,
    PngLimitError,
    PngReadLimits,
)


@pytest.mark.parametrize('color', list(PngColorType))
@pytest.mark.parametrize('interlace', list(PngInterlaceMethod))
def test_decoded_budget_matches_actual_scanlines(color, interlace):
    for depth in color.bit_depths:
        image = PngImage(
            PngHeader((3, 3), depth, color, interlace_method=interlace),
            [[0] * (3 * color.channels) for _row in range(3)],
            palette=[(0, 0, 0)] if color == PngColorType.INDEXED_COLOR else None,
        )
        data = image.dump_to_bytes(filter_type=PngFilterType.NONE)
        document = PngDocument.parse(data)
        expected = len(zlib.decompress(b''.join(chunk.data for chunk in document.find_chunks(b'IDAT'))))
        assert PngImage.parse(data, limits=PngReadLimits(max_decoded_bytes=expected)).bitmap == image.bitmap
        for read in (PngDocument.parse, PngImage.parse):
            with pytest.raises(PngLimitError) as caught:
                read(data, limits=PngReadLimits(max_decoded_bytes=expected - 1))
            assert caught.value.actual == expected
            assert caught.value.limit == 'max_decoded_bytes'
        with pytest.raises(PngLimitError):
            PngImage.from_document(document, limits=PngReadLimits(max_decoded_bytes=expected - 1))


def test_row_budget_counts_actual_nonempty_adam7_passes():
    image = PngImage(PngHeader((3, 1), interlace_method=PngInterlaceMethod.ADAM7), [[1, 2, 3, 255] * 3])
    data = image.dump_to_bytes()
    assert PngImage.parse(data, limits=PngReadLimits(max_row_bytes=4)).bitmap == image.bitmap
    with pytest.raises(PngLimitError) as caught:
        PngImage.parse(data, limits=PngReadLimits(max_row_bytes=3))
    assert caught.value.actual == 4


def test_row_budget_rejects_after_ihdr_before_idat():
    data = PngImage(PngHeader((2, 1)), [[1, 2, 3, 255] * 2]).dump_to_bytes()
    stream = BytesIO(data)
    with pytest.raises(PngLimitError):
        PngImage.parse(stream, limits=PngReadLimits(max_row_bytes=7))
    assert stream.tell() == 33


@pytest.mark.parametrize('default_frame', [False, True])
def test_animation_decoded_budget_is_cumulative_without_double_counting_default(default_frame):
    image = PngImage(
        PngHeader((1, 1)),
        [[1, 2, 3, 255]],
        animation=PngAnimation(
            frames=[PngFrame(PngFrameControl((1, 1)), [[4, 5, 6, 255]])],
            default_image_control=PngFrameControl((1, 1)) if default_frame else None,
        ),
    )
    data = image.dump_to_bytes()
    assert PngImage.parse(data, limits=PngReadLimits(max_decoded_bytes=10)).animation is not None
    with pytest.raises(PngLimitError) as caught:
        PngImage.parse(data, limits=PngReadLimits(max_decoded_bytes=9))
    assert caught.value.actual == 10
