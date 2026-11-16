import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from png import PngIccProfile, PngUnsupportedError, PngValidationError
from png._icc_misc import validate_misc_context


def _profile(assets_dir, changes):
    data = bytearray(assets_dir.joinpath('icc', 'sRGB_v4_ICC_preference.icc').read_bytes())
    data[84:100] = bytes(16)
    for offset, value in changes:
        data[offset:offset + 4] = value
    return bytes(data)


def test_registered_header_signatures_and_advisory_creator(assets_dir):
    for changes in [[(4, b'lcms')], [(4, b'ECMS')], [(48, b'APPL')], [(48, b'ACER'), (52, b'ADA2')],
                    [(52, b'ADA2')], [(80, b'priv')]]:
        PngIccProfile('Registry', _profile(assets_dir, changes)).validate_profile_tags()
    for platform in (bytes(4), b'APPL', b'MSFT', b'SGI ', b'SUNW'):
        PngIccProfile('Platform', _profile(assets_dir, [(40, platform)])).validate_profile_tags()
    with pytest.raises(PngValidationError, match='platform'):
        PngIccProfile('Platform', _profile(assets_dir, [(40, b'TGNT')])).validate_profile_tags()


@pytest.mark.parametrize('changes', [[(4, b'????')], [(48, b'????')], [(52, b'????')],
                                    [(48, b'APPL'), (52, b'ADA2')], [(52, b'6C9C')]])
def test_unknown_or_ambiguous_registration_is_unsupported_not_invalid(assets_dir, changes):
    metadata = PngIccProfile('Unconfirmed', _profile(assets_dir, changes))
    metadata.validate_profile_structure()
    with pytest.raises(PngUnsupportedError, match='2026-11-16 registry snapshot'):
        metadata.validate_profile_tags()


def test_registry_snapshot_provenance_and_reproducible_tables(assets_dir):
    directory = assets_dir.joinpath('icc', 'registry')
    for record in json.loads(directory.joinpath('SOURCE.json').read_text())['files']:
        assert hashlib.sha256(directory.joinpath(record['path']).read_bytes()).hexdigest() == record['sha256']
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('icc_generator', root.joinpath('tools', 'generate_icc_registry.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.generate() == root.joinpath('src', 'png', '_icc_registry_data.py').read_text()


def test_characterization_reference_names_require_exact_registered_spelling():
    for name in (b'FOGRA39', b'CGATS TR 001', b'APTEC Coated CardBoard'):
        validate_misc_context(bytes(128), b'targ', memoryview(b'text' + bytes(4) + b'ICCHDAT ' + name + b'\0'))
    for name in (b'fogra39', b'FOGRA39 ', b'Example'):
        with pytest.raises(PngUnsupportedError, match='registry snapshot'):
            validate_misc_context(bytes(128), b'targ', memoryview(b'text' + bytes(4) + b'ICCHDAT ' + name + b'\0'))
