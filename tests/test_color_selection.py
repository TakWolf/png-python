import pytest

from png import PngChromaticities, PngCicp, PngGamma, PngIccProfile, PngImage, PngSrgb


@pytest.mark.parametrize('raw', [False, True])
@pytest.mark.parametrize(('understood', 'expected'), [
    ((b'cICP', b'iCCP', b'sRGB', b'gAMA', b'cHRM'), [b'cICP']),
    ((b'iCCP', b'sRGB', b'gAMA'), [b'iCCP']),
    ((b'sRGB', b'gAMA', b'cHRM'), [b'sRGB']),
    ((b'gAMA', b'cHRM'), [b'gAMA', b'cHRM']),
    ((b'cHRM',), [b'cHRM']), ((b'gAMA',), [b'gAMA']), ((), []),
])
def test_color_precedence_is_independent_of_chunk_order(png_suite_dir, icc_profile_bytes, raw, understood, expected):
    image = PngImage.load(png_suite_dir.joinpath('basn2c08.png'))
    image.metadata.clear()
    entries = [PngGamma(45455), PngSrgb(), PngIccProfile('Official', icc_profile_bytes),
               PngCicp(9, 16), PngChromaticities((31270, 32900), (64000, 33000), (30000, 60000), (15000, 6000))]
    if raw:
        image.ancillary_chunks.extend(entry.to_chunk() for entry in entries)
    else:
        image.metadata.extend(entries)
    before = [row[:] for row in image.bitmap]
    selected = image.select_color_metadata(understood)
    assert [item.type for item in selected] == expected
    assert image.bitmap == before
    if selected:
        first_type = selected[0].type
        if first_type == b'cICP':
            selected[0].color_primaries = 1
            assert entries[3].color_primaries == 9
        assert image.select_color_metadata(understood)[0] is not selected[0]


def test_unknown_cicp_parameters_can_be_declined_by_the_consumer(png_suite_dir):
    image = PngImage.load(png_suite_dir.joinpath('basn2c08.png'))
    image.metadata.clear()
    image.metadata.extend([PngCicp(255, 255), PngGamma(45455)])
    # A consumer that does not implement these values omits cICP capability.
    assert image.select_color_metadata([b'gAMA'])[0].type == b'gAMA'
    assert image.find_metadata(b'cICP')[0].color_primaries == 255
