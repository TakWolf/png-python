# Web Platform Tests: PNG and APNG

Original files from [web-platform-tests/wpt](https://github.com/web-platform-tests/wpt),
pinned to commit `44d24bce619f53d07b311f2732f2c50adc407399`.

The [W3C PNG Third Edition implementation report](https://w3c.github.io/png/Implementation_Report_3e/)
links these APNG tests. This directory contains the files directly under
`png/apng/`, the complete `png/apng/support/` images, and `png/apng/resources/`
descriptions and generators. The `manual/` directory is not included.

The complete `png/support/` directory (5 PNG images at this commit) is also
included for color, ICC, Exif and transparency tests.

Download URL pattern:
`https://raw.githubusercontent.com/web-platform-tests/wpt/44d24bce619f53d07b311f2732f2c50adc407399/<path>`

Original filenames and contents are retained. `SOURCE.json` records each file's
SHA-256 and Git blob ID. `LICENSE.md` is the upstream license. Original author
credits remain in the HTML and resource files.

Python tests use these files as inputs and compare final rendered images with
the upstream reference PNGs. They do not run a browser, validate playback in
wall-clock time, or claim to run the WPT harness. The `fDAT-inherits-cICP` case
checks inheritance of color metadata; its color-managed display assertion is
outside the current sample-space compositor's scope.
