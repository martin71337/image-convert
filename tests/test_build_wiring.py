"""Pins between the program and the things that package it.

None of this builds an executable - that takes minutes and needs PyInstaller.
What it does is catch the ways the spec, the icon builder and the program can
quietly stop agreeing with each other, each of which produces a bundle that
builds cleanly and misbehaves only once it is in someone's hands.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from imgconv import APP_NAME, APP_PUBLISHER, __version__
from imgconv.gui import icon as icon_module
from imgconv.selftest import LAZY_IMPORTS

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC = REPO_ROOT / "imageconvert.spec"


@pytest.fixture(scope="module")
def spec_source() -> str:
    return SPEC.read_text(encoding="utf-8")


class TestTheSpec:
    def test_the_spec_exists_and_is_committed(self):
        assert SPEC.is_file()

    def test_the_spec_parses(self, spec_source: str):
        """A spec with a syntax error fails minutes into a build, after the
        suite has already passed."""
        ast.parse(spec_source)

    def test_the_spec_collects_the_heif_binaries(self, spec_source: str):
        """The single most consequential line in the build.

        Without it PyInstaller ships pillow_heif's Python module and not
        libheif's DLLs, and the program fails on the first HEIC a user opens -
        which is the only thing it is for.
        """
        assert 'collect_dynamic_libs("pillow_heif")' in spec_source

    def test_the_spec_declares_the_deferred_imports(self, spec_source: str):
        assert "LAZY_IMPORTS" in spec_source
        assert 'collect_submodules("pillow_heif")' in spec_source

    def test_the_spec_does_not_exclude_anything_imgconv_needs(self, spec_source: str):
        """Excluding a module something imports lazily produces a bundle that
        builds cleanly and dies when a user reaches that feature."""
        tree = ast.parse(spec_source)
        excluded: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "excludes":
                for element in getattr(node.value, "elts", []):
                    if isinstance(element, ast.Constant):
                        excluded.add(element.value)

        assert excluded, "the excludes list should be explicit, even if short"
        for name in LAZY_IMPORTS:
            root = name.split(".")[0]
            assert root not in excluded, f"{name} is needed but {root} is excluded"
        for required in ("PySide6.QtWidgets", "PySide6.QtGui", "PySide6.QtCore", "PIL"):
            assert required not in excluded

    def test_the_spec_builds_one_file_not_one_folder(self, spec_source: str):
        """A COLLECT step would produce a folder, not the single portable .exe
        that was asked for."""
        assert "COLLECT" not in spec_source

    def test_upx_is_off(self, spec_source: str):
        """UPX-packed executables trip antivirus heuristics."""
        assert "upx=False" in spec_source
        assert "upx=True" not in spec_source

    def test_the_window_is_not_a_console(self, spec_source: str):
        assert "console=False" in spec_source

    def test_the_spec_reads_the_version_rather_than_restating_it(self, spec_source: str):
        """One version literal. A number typed into the spec would drift."""
        assert "__version__" in spec_source
        assert f'"{__version__}"' not in spec_source, (
            "the spec appears to restate the version literally"
        )

    def test_the_publisher_and_name_come_from_the_package(self, spec_source: str):
        assert "APP_PUBLISHER" in spec_source
        assert "APP_NAME" in spec_source
        assert f'"{APP_PUBLISHER}"' not in spec_source

    def test_the_spec_freezes_a_script_not_a_module(self, spec_source: str):
        """PyInstaller cannot freeze ``python -m package``."""
        assert "launch.py" in spec_source
        assert (REPO_ROOT / "launch.py").is_file()


class TestTheIconWiring:
    def test_the_spec_puts_the_icon_where_the_program_looks(self, spec_source: str):
        """Both sides use the program's own constants rather than a repeated
        string, and this proves the spec did not stop doing so."""
        assert "BUNDLE_SUBDIRECTORY" in spec_source
        assert "ICON_FILENAME" in spec_source

    def test_the_icon_builder_writes_the_name_the_finder_looks_for(self):
        from tools import make_icon

        assert make_icon.DEFAULT_OUTPUT.name == icon_module.ICON_FILENAME

    def test_the_source_candidate_matches_the_builder_s_output(self):
        """A source run finds the icon only if these two agree on the path."""
        from tools import make_icon

        assert make_icon.DEFAULT_OUTPUT in icon_module.icon_candidates()

    def test_the_icon_builds_and_carries_every_size(self, tmp_path: Path):
        from PIL import Image

        from tools import make_icon

        written = make_icon.generate(tmp_path / "test.ico")
        with Image.open(written) as icon:
            carried = {size[0] for size in icon.info["sizes"]}
        assert carried == set(make_icon.ICON_SIZES)

    def test_sixteen_pixels_is_included(self):
        """The size actually seen, in the taskbar and the title bar."""
        from tools import make_icon

        assert 16 in make_icon.ICON_SIZES

    def test_the_icon_is_written_atomically(self, tmp_path: Path):
        """An interrupted build must leave the previous icon or nothing, never a
        truncated one that Explorer would cache."""
        from tools import make_icon

        target = tmp_path / "atomic.ico"
        make_icon.generate(target)
        assert target.is_file()
        assert list(tmp_path.glob("*.partial")) == []


class TestTheSelfTest:
    def test_it_passes_from_source(self, capsys):
        """The same check the build gate runs against the frozen executable."""
        from imgconv.selftest import run

        assert run(verbose=False) == 0
        assert "SELF-TEST PASSED" in capsys.readouterr().out

    def test_every_declared_lazy_import_actually_imports(self):
        import importlib

        for name in LAZY_IMPORTS:
            importlib.import_module(name)

    def test_the_lazy_imports_name_the_decoder(self):
        """If pillow_heif ever falls out of this list, the bundle can ship
        without it and the self-test would no longer notice."""
        assert "pillow_heif" in LAZY_IMPORTS
        assert "imgconv.imaging.backend" in LAZY_IMPORTS


class TestTheLauncher:
    def test_version_prints_and_exits_cleanly(self, capsys):
        from launch import main

        assert main(["--version"]) == 0
        assert __version__ in capsys.readouterr().out

    def test_selftest_is_reachable_from_the_launcher(self, capsys):
        """What ``ImageConvert.exe --selftest`` runs."""
        from launch import main

        assert main(["--selftest"]) == 0
        assert "SELF-TEST PASSED" in capsys.readouterr().out


class TestTheBuildScript:
    def test_it_parses(self):
        source = (REPO_ROOT / "tools" / "build_exe.py").read_text(encoding="utf-8")
        ast.parse(source)

    def test_the_selftest_gate_is_present(self):
        """The gate that proves libheif shipped. Its removal would let a broken
        bundle be published."""
        source = (REPO_ROOT / "tools" / "build_exe.py").read_text(encoding="utf-8")
        assert "--selftest" in source
        assert "gate_selftest" in source

    def test_the_suite_gate_runs_both_modes(self):
        source = (REPO_ROOT / "tools" / "build_exe.py").read_text(encoding="utf-8")
        assert '"-O", "-m", "pytest"' in source

    def test_the_product_is_named_correctly(self):
        assert APP_NAME == "Image Convert"
        assert APP_PUBLISHER == "DMARTIN"
