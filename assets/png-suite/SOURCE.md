# PngSuite

Original test images by Willem van Schaik, obtained from the author's site.

- Version: `PngSuite-2017jul19`
- Author's page: <http://www.schaik.com/pngsuite/>
- Archive: <http://www.schaik.com/pngsuite/PngSuite-2017jul19.tgz>
- Archive SHA-256: `0294b244c95a8342c01b00010cf34abdcabc7c6a34fd0fe1bd963917537bfdc8`
- PNG website reference: <https://www.libpng.org/pub/png/pngsuite.html>

The complete archive is extracted here with original names and unmodified
contents, including `PngSuite.README` and `PngSuite.LICENSE`. The author's site
was accessible over HTTP; HTTPS failed during retrieval. The hash records the
downloaded artifact for reproducibility, rather than authenticating its origin.

Files beginning with `x` are deliberately invalid test inputs. Interpret expected
behavior using the author's descriptions and the PNG specification, rather than
assuming every `.png` file is valid.

The initial model tests read IHDR fields from the basic `basn` / `basi` images.
They do not yet test pixel decoding or claim coverage of the full suite.
