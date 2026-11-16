from png import PngCicp, PngContentLightLevel, PngImage, PngMasteringDisplayColorVolume


def test_hdr_unknown_and_outside_nominal_values_are_not_rejected(png_suite_dir):
    # ST 2086 5.2 explicitly permits out-of-nominal values for other purposes.
    # PNG specifies the wire representation; zero cLLI values mean unknown.
    image = PngImage.load(png_suite_dir.joinpath('basn2c08.png'))
    mastering = PngMasteringDisplayColorVolume((65535, 0), (0, 65535), (0, 0), (0, 0), 0, 0)
    image.metadata.extend([PngCicp(2, 2), mastering, PngContentLightLevel(0, 0)])
    restored = PngImage.parse(image.dump_to_bytes())
    assert restored.find_metadata(b'mDCV')[0].to_chunk().data == mastering.to_chunk().data
    light = restored.find_metadata(b'cLLI')[0]
    assert light.maximum_content_light_level == light.maximum_frame_average_light_level == 0


def test_png_hdr_precision_is_preserved_before_any_display_interpretation():
    mastering = PngMasteringDisplayColorVolume((35401, 14602), (8501, 39852), (6551, 2302),
                                              (15636, 16451), 801234, 5)
    restored = PngMasteringDisplayColorVolume.from_chunk(mastering.to_chunk())
    assert restored.maximum_luminance == 801234
    assert restored.red == (35401, 14602)
    assert restored.to_chunk().data == mastering.to_chunk().data
