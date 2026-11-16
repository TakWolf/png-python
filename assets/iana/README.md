# IANA language registry snapshots

These original IANA data files support offline validation of PNG iTXt language
tags. Exact source URLs, registry dates, retrieval dates and SHA-256 digests are
recorded in `SOURCE.json`; upstream records, descriptions and attribution remain
unchanged in the snapshots.

`language-subtag-registry.txt` supplies registered languages, extlangs, scripts,
regions, variants, grandfathered tags and reserved private-use ranges.
`language-tag-extensions-registry.txt` supplies allocated extension singletons.

Only the derived lookup tables in `src/png/_language_data.py` ship with the
runtime package. Regenerate them from the repository root with:

```shell
uv run -m tools.generate_language_registry
```

The script uses Ruff from the development dependencies to format the generated
module according to `pyproject.toml`.

This maintenance script has no network access. To update the snapshot, fetch the
original files from the URLs in `SOURCE.json`, update their provenance, regenerate
the tables, and review the tests and changes. A test verifies that the generated
module exactly matches the committed snapshots.

Validation follows RFC 5646 structure and these fixed registry versions. It
preserves input case and deprecated registrations. It does not canonicalize tags
or validate extension-specific payload semantics from Unicode/CLDR or other
extension standards.
