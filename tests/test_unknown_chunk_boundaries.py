"""Unknown-chunk placement and preservation across valid critical edits."""

import pytest

from png import PngChunk, PngColorType, PngDocument, PngHeader, PngImage, PngValidationError


def _document(kind: bytes, position: str) -> PngDocument:
    document = PngImage(
        PngHeader((1, 1), color_type=PngColorType.TRUECOLOR), [[1, 2, 3]], palette=[(1, 2, 3)]
    ).to_document()
    palette = next(index for index, chunk in enumerate(document.chunks) if chunk.type == b'PLTE')
    idat = next(index for index, chunk in enumerate(document.chunks) if chunk.type == b'IDAT')
    index = {'before_palette': palette, 'after_palette': palette + 1, 'after_idat': idat + 1}[position]
    document.chunks.insert(index, PngChunk(kind, b'preserve this payload'))
    return PngDocument.parse(document.dump_to_bytes())


@pytest.mark.parametrize('kind', [b'vpAg', b'vpAG'])
@pytest.mark.parametrize('position', ['before_palette', 'after_palette', 'after_idat'])
@pytest.mark.parametrize('edit', ['none', 'palette', 'split_idat'])
def test_unknown_preservation_and_location_across_critical_edits(kind, position, edit):
    document = _document(kind, position)
    if edit == 'palette':
        document.find_chunks(b'PLTE')[0].data = bytes([3, 2, 1])
    elif edit == 'split_idat':
        index = next(index for index, chunk in enumerate(document.chunks) if chunk.type == b'IDAT')
        payload = document.chunks[index].data
        document.chunks[index : index + 1] = [PngChunk(b'IDAT', payload[:1]), PngChunk(b'IDAT', payload[1:])]
    output = PngDocument.parse(document.dump_to_bytes())
    kept = output.find_chunks(kind)
    assert bool(kept) == (kind == b'vpAg' or edit == 'none')
    if kept:
        assert kept[0].data == b'preserve this payload'
        kinds = [chunk.type for chunk in output.chunks]
        if position == 'before_palette':
            assert kinds.index(kind) < kinds.index(b'PLTE')
        elif position == 'after_palette':
            assert kinds.index(b'PLTE') < kinds.index(kind) < kinds.index(b'IDAT')
        else:
            assert kinds.index(kind) > max(index for index, chunk in enumerate(output.chunks) if chunk.type == b'IDAT')
    assert len(document.find_chunks(kind)) == 1
    assert PngImage.from_document(output).bitmap == [[1, 2, 3]]


@pytest.mark.parametrize('kind', [b'vpAg', b'vpAG'])
@pytest.mark.parametrize('reconstruct', [False, True])
def test_unknown_movement_across_plte_respects_the_safe_to_copy_bit(kind, reconstruct):
    document = _document(kind, 'after_palette')
    original = document.find_chunks(kind)[0]
    document.chunks.remove(original)
    moved = PngChunk(kind, original.data) if reconstruct else original
    palette = next(index for index, chunk in enumerate(document.chunks) if chunk.type == b'PLTE')
    document.chunks.insert(palette, moved)
    if kind == b'vpAG':
        with pytest.raises(PngValidationError, match='cannot move unknown'):
            document.dump_to_bytes()
    else:
        output = PngDocument.parse(document.dump_to_bytes())
        kinds = [chunk.type for chunk in output.chunks]
        assert kinds.index(kind) < kinds.index(b'PLTE') < kinds.index(b'IDAT')
