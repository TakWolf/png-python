from copy import deepcopy

import pytest

from png import PngChunk, PngDocument, PngHeader, PngImage, PngText


@pytest.mark.parametrize('copy_items', [False, True])
def test_reencoding_preserves_metadata_positions_and_drops_unsafe_chunks(copy_items):
    source = PngImage(PngHeader((1, 1)), [[1, 2, 3, 255]]).to_document()
    chunks = [
        source.chunks[0],
        PngText('k', 'before').to_chunk(),
        PngChunk(b'vpAg', b'before'),
        *source.find_chunks(b'IDAT'),
        PngText('k', 'after').to_chunk(),
        PngChunk(b'vpAg', b'after'),
        PngChunk(b'vpAG', b'unsafe'),
        source.chunks[-1],
    ]
    image = PngImage.parse(PngDocument(chunks).dump_to_bytes())
    if copy_items:
        image.metadata = deepcopy(image.metadata)
        image.ancillary_chunks = deepcopy(image.ancillary_chunks)
    image.bitmap[0][0] = 255
    output = image.to_document().chunks
    idat = next(index for index, chunk in enumerate(output) if chunk.type == b'IDAT')
    assert [(chunk.type, chunk.data) for chunk in output[:idat] if chunk.type != b'IHDR'] == [
        (b'tEXt', b'k\0before'),
        (b'vpAg', b'before'),
    ]
    assert [(chunk.type, chunk.data) for chunk in output[idat + 1 :] if chunk.type != b'IEND'] == [
        (b'tEXt', b'k\0after'),
        (b'vpAg', b'after'),
    ]


def test_identical_repeated_metadata_remains_repeated_after_copy():
    image = PngImage(PngHeader((1, 1)), [[1, 2, 3, 255]], metadata=[PngText('k', 'same') for _index in range(100)])
    image = PngImage.parse(image.dump_to_bytes())
    image.metadata = deepcopy(image.metadata)
    image.metadata[0].text = 'edited'
    image = PngImage.parse(image.dump_to_bytes())
    assert [item.text for item in image.metadata] == ['edited'] + ['same'] * 99


@pytest.mark.parametrize('copied_indices', [(0,), (1,), (0, 1)])
def test_identical_unknown_chunks_keep_each_original_side_when_reconstructed(copied_indices):
    source = PngImage(PngHeader((1, 1)), [[1, 2, 3, 255]]).to_document()
    document = PngDocument(
        [
            source.chunks[0],
            PngChunk(b'vpAg', b'same'),
            *source.find_chunks(b'IDAT'),
            PngChunk(b'vpAg', b'same'),
            source.chunks[-1],
        ]
    )
    image = PngImage.parse(document.dump_to_bytes())
    for index in copied_indices:
        image.ancillary_chunks[index] = deepcopy(image.ancillary_chunks[index])
    output = image.to_document().chunks
    assert [chunk.type for chunk in output] == [b'IHDR', b'vpAg', b'IDAT', b'vpAg', b'IEND']
