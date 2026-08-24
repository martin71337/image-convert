# Image Convert

A Windows desktop tool that converts images — principally the HEIC photographs an
iPhone produces — into JPEG, one at a time or a folder at a time, with nothing
uploaded anywhere.

Publisher: **DMARTIN**

## Why

Field photographs come off a phone as HEIC. Nothing downstream will take them:
`python-docx` will not embed one, Word will not place one, and the report
pipelines all expect JPEG. This converts them locally, keeps the capture date
that a photo log is keyed to, and gets the colour right.

## Using it

Run `ImageConvert.exe`. Nothing to install — copy it wherever you like.

1. Drop images or folders onto the window, or use **Add files** / **Add folder**.
2. Check the **Type** column. It shows what each file *actually is*, which is not
   always what its name claims.
3. Pick a target format and press **Convert**.

Converted files go to a `converted` folder beside each original by default, so
the originals are never touched and the new files are easy to collect. The other
choices are the source folder itself, or one folder of your own.

### What it does to a photo

| | |
|---|---|
| **Capture date, camera, GPS** | Kept. Unrecoverable once dropped, so it is on by default. |
| **Colour** | Converted from the phone's Display P3 into sRGB, so it looks right in Word, browsers and print rather than oversaturated. |
| **Rotation** | Applied to the pixels, and the file then declares itself upright — so it does not come out sideways in the next application. |
| **Existing files** | Never silently overwritten. A second conversion writes `IMG_2480_1.jpg`. |
| **Transparency** | Flattened onto white when the target is JPEG, which cannot store it. Kept for PNG. |

A file that is already the format you asked for is skipped rather than
re-encoded, since re-encoding a JPEG as a JPEG loses quality for nothing.

### Formats

Reads HEIC/HEIF, JPEG, PNG, TIFF, WebP and BMP. Writes JPEG and PNG.

AVIF and GIF are recognised and named correctly in the queue, but have no
conversion registered, so they are refused by name rather than half-handled.

## Building it

Needs Python 3.14 on Windows.

```bash
py -m venv .venv
```

```bash
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

```bash
.venv\Scripts\python.exe tools/build_exe.py
```

That produces `dist\ImageConvert.exe` and a `.sha256` beside it. The build
refuses to finish unless the suite passes in both modes, the version carries no
pre-release marker, and — the gate that matters — **the executable it just built
passes its own `--selftest`**, which converts a real HEIC inside the real bundle.
Without that gate a bundle can build, start, show its window, and fail on the
first photo a user opens, because PyInstaller collected `pillow_heif` but not
libheif's DLLs.

Run from source with `py launch.py`; check a bundle with
`ImageConvert.exe --selftest`.

## How it is put together

```
imgconv/
  formats.py     format records, and identifying a file by its CONTENT
  pathways.py    the registry: which conversions exist
  options.py     one record holding everything the user asked for
  naming.py      output paths, and the never-overwrite rule
  convert.py     one file in, one file out - the single entry point
  job.py         batches, on several threads, with progress and cancel
  imaging/       THE ONLY place Pillow is imported
  gui/           PySide6; computes nothing
```

Two rules hold the shape:

**`imgconv/gui` never computes a result.** It builds a `ConversionOptions` and
calls `job.run` — the same function a script or a test would call. No bug in the
interface can produce a different conversion, only a different request.

**New conversions are registry entries, not new code.** `pathways.ALL_PATHWAYS`
is a declared table, and the interface's target list is derived from it. Adding
HEIC → PDF, a resized copy, or a watermarked one means adding a record and the
function it names — the job runner and the window do not change. There is a test
that adds a pathway and asserts it shows up, so the seam cannot quietly rot.

## Notes worth keeping

- **`page2.HEIC` in Downloads is a JPEG.** Files are routed by their leading
  bytes, never their extension; when the two disagree the file still converts and
  the queue says so.
- **pillow-heif already normalises HEIC orientation** and hands over pre-rotated
  pixels tagged upright. The double-rotation trap therefore lives on the TIFF and
  PNG pathways, not the HEIC one.
- **Pillow's TIFF writer is not a faithful fixture.** It applies an EXIF
  orientation by rotating the pixels and dropping the tag, and does not carry an
  EXIF sub-IFD through. Tests that need real metadata use PNG or WebP.
- **`pillow_heif.register_avif_opener` no longer exists** at 1.x; Pillow handles
  AVIF natively now. Calling it raises `AttributeError`.
