# Image Convert

Windows tool that converts HEIC photos (and TIFF, PNG, WebP, BMP) to JPEG or PNG, one file or a whole folder. Runs locally; nothing is uploaded.

## Use

Download the zip from [Releases](https://github.com/martin71337/image-convert/releases), unzip, run `ImageConvert.exe`. No install. Windows will warn about an unsigned app the first time (More info, then Run anyway).

1. Drop in files or folders, or use Add files / Add folder.
2. Pick a format and press Convert.

Converted files go in a `converted` folder next to the originals. Originals are never changed, and existing files are never overwritten (a second run writes `IMG_2480_1.jpg`).

Photos keep their capture date, camera and GPS data, are converted from Display P3 to sRGB, and have rotation applied to the pixels. Transparency is flattened to white for JPEG. Files already in the target format are skipped. File types are detected from the file contents, not the extension.

AVIF and GIF are recognised but not converted.

## Build

Needs Python 3.14 on Windows.

```bash
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe tools/build_exe.py
```

This produces `dist\ImageConvert.exe` and a `.sha256`. The build fails unless the tests pass and the built exe passes its own `--selftest`. Run from source with `py launch.py`.

## Layout

`imgconv/` holds the conversion code, `imgconv/imaging/` is the only place Pillow is used, and `imgconv/gui/` is the PySide6 window, which only builds a request and calls `job.run`. New conversions are added as entries in `imgconv/pathways.py`.
