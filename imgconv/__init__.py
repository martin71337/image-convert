"""Image Convert - a desktop image conversion tool.

The package is named ``imgconv``; the product is named "Image Convert". The two
differ on purpose: a Python package may not contain a space, and renaming the
product later should not mean renaming every import in the project.

Layering, enforced in review:

* ``imgconv.imaging`` is the ONLY place ``PIL`` or ``pillow_heif`` is imported.
  Everything above it works in paths, records and enums, which is what makes the
  engine testable without a decoder and swappable without a rewrite.
* ``imgconv.gui`` never computes a result. It builds a
  :class:`~imgconv.options.ConversionOptions` and calls :func:`imgconv.job.run`.
* Everything else in the package is standard library only.
"""

from __future__ import annotations

APP_NAME = "Image Convert"
"""The product name. Window title, version resource, About text."""

APP_PUBLISHER = "DMARTIN"
"""CompanyName in the Windows version resource, and the publisher a future
installer would file the program under."""

APP_DESCRIPTION = "Convert HEIC and other images to JPEG"

__version__ = "0.1.0"
"""THE version literal. Nothing else in the project states a version.

``imageconvert.spec`` imports this to build the Windows version resource, and
``tools/build_exe.py`` refuses to build a release while a pre-release marker
(``-dev``) is present, so the number Explorer shows cannot disagree with the
number the build gate checked.
"""

__all__ = ["APP_NAME", "APP_PUBLISHER", "APP_DESCRIPTION", "__version__"]
