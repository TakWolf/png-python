import zlib

import pytest

from png import PngColorType, PngHeader, PngImage, PngInterlaceMethod


@pytest.mark.parametrize('interlace', list(PngInterlaceMethod))
@pytest.mark.parametrize('depth', [8, 16])
def test_first_row_and_one_pixel_filters_preserve_average(depth, interlace):
    scale = 257 if depth == 16 else 1
    image = PngImage(
        PngHeader((1, 2), depth, PngColorType.GRAYSCALE, interlace_method=interlace),
        [[200 * scale], [100 * scale]],
    )
    document = image.to_document()
    assert PngImage.from_document(document).bitmap == image.bitmap
    if depth == 8 and interlace == PngInterlaceMethod.NONE:
        assert zlib.decompress(b''.join(chunk.data for chunk in document.find_chunks(b'IDAT'))) == bytes([0, 200, 3, 0])


def test_single_row_average_is_not_pruned():
    image = PngImage(PngHeader((2, 1), 8, PngColorType.GRAYSCALE), [[200, 100]])
    document = image.to_document()
    assert zlib.decompress(b''.join(chunk.data for chunk in document.find_chunks(b'IDAT'))) == bytes([3, 200, 0])
