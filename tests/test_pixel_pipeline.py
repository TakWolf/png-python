import zlib
from random import Random

import pytest

import png._pixels as pixels
from png import (
    PngAnimation,
    PngChunk,
    PngDocument,
    PngFilterType,
    PngFrame,
    PngFrameControl,
    PngHeader,
    PngImage,
    PngInterlaceMethod,
    PngParseError,
)


@pytest.mark.parametrize('size', [1, 7, 17, 65536])
@pytest.mark.parametrize('interlace', list(PngInterlaceMethod))
def test_compression_blocks_preserve_single_stream_and_frame_sequence(size, interlace):
    random = Random(0)
    bitmap = [[random.randrange(256) for _sample in range(64 * 4)] for _row in range(64)]
    image = PngImage(
        PngHeader((64, 64), interlace_method=interlace),
        bitmap,
        animation=PngAnimation(frames=[PngFrame(PngFrameControl((64, 64)), bitmap)]),
    )
    document = image.to_document(filter_type=PngFilterType.NONE, idat_chunk_size=size)
    idat = document.find_chunks(b'IDAT')
    fdat = document.find_chunks(b'fdAT')
    assert all(chunk.length == size for chunk in idat[:-1])
    assert 0 < idat[-1].length <= size
    assert all(chunk.length == size + 4 for chunk in fdat[:-1])
    assert 4 < fdat[-1].length <= size + 4
    compressed = b''.join(chunk.data for chunk in idat)
    assert b''.join(chunk.data[4:] for chunk in fdat) == compressed
    assert zlib.decompress(compressed)
    restored = PngImage.from_document(document)
    assert restored.bitmap == bitmap
    assert restored.animation.frames[0].bitmap == bitmap


@pytest.mark.parametrize('size', [1, 7, 65536])
@pytest.mark.parametrize('damage', ['checksum', 'truncate', 'extra_scanline'])
def test_pixel_pipeline_validates_complete_stream(size, damage):
    header = PngHeader((1, 1))
    encoded = zlib.compress(b'\0\x01\x02\x03\xff')
    if damage == 'checksum':
        encoded = encoded[:-1] + bytes([encoded[-1] ^ 1])
    elif damage == 'truncate':
        encoded = encoded[:-1]
    else:
        encoded = zlib.compress(b'\0\x01\x02\x03\xffextra')
    chunks = [header.to_chunk()]
    chunks.extend(PngChunk(b'IDAT', encoded[offset : offset + size]) for offset in range(0, len(encoded), size))
    chunks.append(PngChunk(b'IEND'))
    document = PngDocument(chunks)
    with pytest.raises(PngParseError):
        PngImage.from_document(document)


def test_truncated_large_image_is_rejected_before_bitmap_allocation(monkeypatch):
    header = PngHeader((1000000, 1000000), interlace_method=PngInterlaceMethod.ADAM7)

    def unexpected_allocation(*args, **kwargs):
        pytest.fail('must verify scanline extent before allocating bitmap rows')

    monkeypatch.setattr(pixels, '_empty_row', unexpected_allocation)
    monkeypatch.setattr(pixels, '_unpack_samples', unexpected_allocation)
    with pytest.raises(PngParseError):
        pixels.decode_pixels(header, [zlib.compress(b'\0')], compact=True)


def test_inflater_does_not_accumulate_the_complete_output():
    original = b'a' * 200000
    blocks = list(pixels._inflate_parts([zlib.compress(original)], len(original)))
    assert max(map(len, blocks)) <= 65536
    assert b''.join(blocks) == original
