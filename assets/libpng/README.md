# libpng test PNG fixtures

These unmodified PNG files come from the official libpng repository's
`v1.6.59` release, commit
`cd952f49f95bb27154ae77dbb103032d95f6e580`.
[SOURCE.json](SOURCE.json) records each upstream path and SHA-256 digest.

- The 104 PNG files at this directory's root are the generated color-type,
  bit-depth, gamma-signaling and transparency matrix. Tests check the known
  sample pattern independently, preserve metadata, and expand RGBA without
  applying display gamma or color-space conversion. Their embedded licensing
  text dedicates the generated images to CC0 1.0.
- `ch1n3p04.png` and `ch2n3p08.png` are the other two root PNG files. Tests
  compare their hIST entries with independently counted palette-index usage.
- `png-3/`: one indexed Display P3 cICP sample. Tests check signaling and raw
  sample preservation; they do not compare color-managed display output.
- `badpal/`: nine short-palette regression images. They exercise palette
  indices outside the available PLTE entries. This library follows PNG Third
  Edition section 13.1 and displays such indices as opaque black.
- `crashers/`: 23 malformed inputs, including invalid CRC/Adler checksums,
  empty ancillary chunks and huge advertised lengths. Tests check rejection
  and bounded reads; the filenames do not guarantee which error occurs first.
  In particular, `bad_iCCP.png` already has an invalid IHDR CRC.

All 139 upstream `contrib/testpngs/` PNG files are stored here at identical
relative paths with unmodified bytes, including files also present in
`assets/pngsuite/`. Keep this complete PNG set in sync when updating the
pinned libpng reference; SOURCE.json and its integrity test cover every file.
Some 16-bit files named `*-tRNS.png` contain no tRNS chunk; tests follow the
actual chunk contents.

The upstream root `LICENSE` ([local copy](LICENSE.txt)) and
`contrib/README.txt` ([local copy](CONTRIB-NOTICE.txt)) are retained verbatim.
The contrib notice states that contributions need not all share libpng's
license; these fixtures are not relicensed under this project's MIT license.

Only image data and notices are included. Tests use Python and the standard
library, without building, loading or invoking libpng or any C test program.
