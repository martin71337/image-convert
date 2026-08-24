"""The one window.

There is deliberately no single/multiple mode switch. Converting one photo is
converting a queue of one, and a mode selector would be a control whose only
effect is to make the user classify their own task before the program will help.
Files arrive by button or by being dropped on the window; everything downstream
is identical.

The interface computes nothing. Every label it shows about formats comes from the
format records, every target it offers comes from the pathway registry, and the
conversion itself is :func:`imgconv.job.run` on a worker thread.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSlider,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from imgconv import APP_NAME, __version__, formats, job, pathways
from imgconv.gui.icon import icon_path
from imgconv.gui.queue_model import QueueModel
from imgconv.gui.worker import ConversionWorker, JobReportBuilder
from imgconv.options import (
    DEFAULT_QUALITY,
    MAX_QUALITY,
    MIN_QUALITY,
    SUBFOLDER_NAME,
    CollisionPolicy,
    ConversionOptions,
    OutputLocation,
)

COLLISION_LABELS = {
    CollisionPolicy.SUFFIX: "Add a number to the new file",
    CollisionPolicy.SKIP: "Leave the existing file alone",
    CollisionPolicy.OVERWRITE: "Replace the existing file",
}
"""Plain wording for each policy. The enum member is what is stored; these
strings exist only on screen, so renaming one cannot change behaviour."""


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.resize(940, 680)

        found = icon_path()
        if found is not None:
            self.setWindowIcon(QIcon(str(found)))

        self.model = QueueModel(self)
        self.worker: ConversionWorker | None = None
        self.builder = JobReportBuilder()
        self.last_output_folder: Path | None = None

        self._build()
        self._connect()
        self._refresh_targets()
        self._update_enabled()

    # -- construction -------------------------------------------------------

    def _build(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        layout.addLayout(self._build_queue_buttons())
        layout.addWidget(self._build_table(), stretch=1)
        layout.addWidget(self.detail_label)
        layout.addWidget(self._build_settings())
        layout.addLayout(self._build_action_row())

        self.setCentralWidget(central)
        self.statusBar().showMessage(f"{APP_NAME} {__version__}")

    def _build_queue_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.add_files_button = QPushButton("Add files...")
        self.add_folder_button = QPushButton("Add folder...")
        self.remove_button = QPushButton("Remove")
        self.clear_button = QPushButton("Clear")
        self.recurse_check = QCheckBox("Include subfolders")
        self.recurse_check.setChecked(True)

        for widget in (
            self.add_files_button,
            self.add_folder_button,
            self.remove_button,
            self.clear_button,
        ):
            row.addWidget(widget)
        row.addSpacing(12)
        row.addWidget(self.recurse_check)
        row.addStretch(1)
        return row

    def _build_table(self) -> QTableView:
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QueueModel.NAME, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(QueueModel.FOLDER, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(QueueModel.SIZE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(QueueModel.TYPE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(QueueModel.STATUS, QHeaderView.ResizeMode.ResizeToContents)

        self.detail_label = QLabel("Drop images or folders here, or use Add files.")
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet("color: palette(mid);")
        self.detail_label.setMinimumHeight(34)
        return self.table

    def _build_settings(self) -> QGroupBox:
        """The settings panel.

        Laid out to be WIDE AND SHORT on purpose. Every row this panel claims is
        a row the file list loses, and the file list is the part the user reads
        while a batch runs. The three preservation checkboxes sit on one line
        beneath the two columns rather than stacking under the destination
        radios, which is what kept the table down to six visible rows.
        """
        box = QGroupBox("Conversion")
        box.setSizePolicy(box.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Fixed)
        column = QVBoxLayout(box)
        column.setSpacing(8)

        outer = QHBoxLayout()
        outer.setSpacing(24)
        column.addLayout(outer)

        # -- left: format and quality
        left = QFormLayout()
        left.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.target_combo = QComboBox()
        left.addRow("Convert to:", self.target_combo)

        quality_row = QHBoxLayout()
        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(MIN_QUALITY, MAX_QUALITY)
        self.quality_slider.setValue(DEFAULT_QUALITY)
        self.quality_slider.setMinimumWidth(150)
        self.quality_value = QLabel(str(DEFAULT_QUALITY))
        self.quality_value.setMinimumWidth(28)
        quality_row.addWidget(self.quality_slider)
        quality_row.addWidget(self.quality_value)
        self.quality_label_widget = QLabel("Quality:")
        left.addRow(self.quality_label_widget, quality_row)

        self.collision_combo = QComboBox()
        for policy in (CollisionPolicy.SUFFIX, CollisionPolicy.SKIP, CollisionPolicy.OVERWRITE):
            self.collision_combo.addItem(COLLISION_LABELS[policy], policy)
        left.addRow("If a file exists:", self.collision_combo)

        # -- right: destination and what to preserve
        right = QVBoxLayout()
        right.addWidget(QLabel("Save converted files to:"))

        self.location_group = QButtonGroup(self)
        self.subfolder_radio = QRadioButton(f'A "{SUBFOLDER_NAME}" folder beside each original')
        self.alongside_radio = QRadioButton("The same folder as the original")
        self.chosen_radio = QRadioButton("This folder:")
        self.subfolder_radio.setChecked(True)
        for index, radio in enumerate(
            (self.subfolder_radio, self.alongside_radio, self.chosen_radio)
        ):
            self.location_group.addButton(radio, index)
            right.addWidget(radio)

        chosen_row = QHBoxLayout()
        chosen_row.addSpacing(20)
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("No folder chosen")
        self.browse_button = QPushButton("Browse...")
        chosen_row.addWidget(self.folder_edit, stretch=1)
        chosen_row.addWidget(self.browse_button)
        right.addLayout(chosen_row)

        right.addStretch(1)

        outer.addLayout(left)
        outer.addLayout(right, stretch=1)

        checks = QHBoxLayout()
        checks.setSpacing(18)
        self.metadata_check = QCheckBox("Keep photo information (date, camera, GPS)")
        self.srgb_check = QCheckBox("Convert colour to sRGB")
        self.rotate_check = QCheckBox("Rotate upright automatically")
        for check in (self.metadata_check, self.srgb_check, self.rotate_check):
            check.setChecked(True)
            checks.addWidget(check)
        checks.addStretch(1)
        column.addLayout(checks)

        return box

    def _build_action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.summary_label = QLabel("")

        self.convert_button = QPushButton("Convert")
        self.convert_button.setDefault(True)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setVisible(False)
        self.open_button = QPushButton("Open output folder")
        self.open_button.setEnabled(False)

        row.addWidget(self.progress, stretch=1)
        row.addWidget(self.summary_label, stretch=1)
        row.addWidget(self.open_button)
        row.addWidget(self.cancel_button)
        row.addWidget(self.convert_button)
        return row

    def _connect(self) -> None:
        self.add_files_button.clicked.connect(self.choose_files)
        self.add_folder_button.clicked.connect(self.choose_folder)
        self.remove_button.clicked.connect(self.remove_selected)
        self.clear_button.clicked.connect(self.clear_queue)
        self.browse_button.clicked.connect(self.choose_output_folder)
        self.convert_button.clicked.connect(self.start_conversion)
        self.cancel_button.clicked.connect(self.cancel_conversion)
        self.open_button.clicked.connect(self.open_output_folder)

        self.quality_slider.valueChanged.connect(
            lambda value: self.quality_value.setText(str(value))
        )
        self.target_combo.currentIndexChanged.connect(self._on_target_changed)
        self.location_group.idToggled.connect(lambda *_: self._update_enabled())
        self.model.dataChanged.connect(lambda *_: self._update_enabled())
        self.model.rowsInserted.connect(lambda *_: self._on_queue_changed())
        self.model.rowsRemoved.connect(lambda *_: self._on_queue_changed())
        self.model.modelReset.connect(self._on_queue_changed)
        self.table.selectionModel().selectionChanged.connect(self._show_detail)

        QShortcut(QKeySequence.StandardKey.Delete, self.table, self.remove_selected)

    # -- queue ---------------------------------------------------------------

    def choose_files(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in formats.readable_extensions())
        chosen, _ = QFileDialog.getOpenFileNames(
            self,
            "Choose images",
            "",
            f"Images ({patterns});;All files (*)",
        )
        if chosen:
            self._add([Path(p) for p in chosen])

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder of images")
        if folder:
            self._add([Path(folder)])

    def _add(self, roots: list[Path]) -> None:
        found = job.collect_images(roots, recurse=self.recurse_check.isChecked())
        if not found:
            self.statusBar().showMessage("Nothing there this program can convert.", 6000)
            return
        added = self.model.add_paths(found)
        skipped = len(found) - added
        message = f"Added {added} file{'s' if added != 1 else ''}."
        if skipped:
            message += f" {skipped} were already in the list."
        self.statusBar().showMessage(message, 6000)

    def remove_selected(self) -> None:
        rows = [i.row() for i in self.table.selectionModel().selectedRows()]
        self.model.remove_rows(rows)

    def clear_queue(self) -> None:
        self.model.clear()

    def _on_queue_changed(self) -> None:
        self._refresh_targets()
        self._update_enabled()

    def _show_detail(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self.detail_label.setText("")
            return
        entry = self.model.entry_at(rows[0].row())
        self.detail_label.setText(entry.detail if entry else "")

    # -- drag and drop -------------------------------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt's naming
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile() and url.toLocalFile()
        ]
        if paths:
            self._add(paths)
            event.acceptProposedAction()

    # -- settings ------------------------------------------------------------

    def _refresh_targets(self) -> None:
        """Rebuild the target list from the registry and what is queued.

        THE reason a new pathway needs no change here: the offered targets are
        the intersection of what every queued format can reach, straight out of
        :func:`imgconv.pathways.common_targets`. Nothing in this file names a
        format.
        """
        previous = self.target_combo.currentData()
        queued = self.model.queued_formats()
        available = (
            pathways.common_targets(queued) if queued else (formats.JPEG, formats.PNG)
        )

        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        for image_format in available:
            self.target_combo.addItem(image_format.label, image_format)
        if previous is not None:
            restored = self.target_combo.findData(previous)
            if restored >= 0:
                self.target_combo.setCurrentIndex(restored)
        self.target_combo.blockSignals(False)

        if not available and queued:
            self.detail_label.setText(
                "These files have no conversion in common. Remove the odd one out, "
                "or convert them in separate batches."
            )

        self.model.plan_for_target(self.current_target())

    def _on_target_changed(self) -> None:
        self.model.plan_for_target(self.current_target())
        self._update_enabled()

    def current_target(self):
        return self.target_combo.currentData()

    def _current_pathways_are_lossy(self) -> bool:
        target = self.current_target()
        if target is None:
            return False
        queued = self.model.queued_formats() or (formats.HEIC,)
        for source in queued:
            for pathway in pathways.ALL_PATHWAYS:
                if pathway.source is source and pathway.target is target and pathway.lossy:
                    return True
        return False

    def _update_enabled(self) -> None:
        running = self.worker is not None and self.worker.isRunning()
        has_files = bool(self.model.convertible_paths())
        has_target = self.current_target() is not None

        self.convert_button.setEnabled(has_files and has_target and not running)
        for widget in (
            self.add_files_button,
            self.add_folder_button,
            self.remove_button,
            self.clear_button,
            self.target_combo,
            self.collision_combo,
            self.metadata_check,
            self.srgb_check,
            self.rotate_check,
            self.subfolder_radio,
            self.alongside_radio,
            self.chosen_radio,
        ):
            widget.setEnabled(not running)

        chosen = self.chosen_radio.isChecked()
        self.folder_edit.setEnabled(chosen and not running)
        self.browse_button.setEnabled(chosen and not running)

        # Quality means nothing for a lossless target; grey it rather than offer
        # a control that does nothing.
        lossy = self._current_pathways_are_lossy()
        self.quality_slider.setEnabled(lossy and not running)
        self.quality_value.setEnabled(lossy and not running)
        self.quality_label_widget.setEnabled(lossy and not running)

    def choose_output_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose an output folder")
        if folder:
            self.folder_edit.setText(folder)

    def current_options(self) -> ConversionOptions:
        """Build the engine's request from what is on screen."""
        if self.subfolder_radio.isChecked():
            location, folder = OutputLocation.SUBFOLDER, None
        elif self.alongside_radio.isChecked():
            location, folder = OutputLocation.ALONGSIDE, None
        else:
            text = self.folder_edit.text().strip()
            location, folder = OutputLocation.CHOSEN, Path(text) if text else None

        return ConversionOptions(
            target_format=self.current_target(),
            quality=self.quality_slider.value(),
            output_location=location,
            output_folder=folder,
            collision=self.collision_combo.currentData(),
            keep_metadata=self.metadata_check.isChecked(),
            convert_to_srgb=self.srgb_check.isChecked(),
            auto_rotate=self.rotate_check.isChecked(),
        )

    # -- running -------------------------------------------------------------

    def start_conversion(self) -> None:
        sources = self.model.convertible_paths()
        if not sources:
            return

        try:
            options = self.current_options()
            options.validate()
        except ValueError as error:
            QMessageBox.warning(self, APP_NAME, str(error))
            return

        self.model.reset_statuses()
        self.builder = JobReportBuilder()
        self.last_output_folder = None

        self.progress.setRange(0, len(sources))
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.cancel_button.setVisible(True)
        self.cancel_button.setEnabled(True)
        self.convert_button.setVisible(False)
        self.open_button.setEnabled(False)
        self.summary_label.setText(f"Converting 0 of {len(sources)}...")

        self.worker = ConversionWorker(sources, options, self)
        self.worker.progressed.connect(self._on_progress)
        self.worker.completed.connect(self._on_completed)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()
        self._update_enabled()

    def cancel_conversion(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.cancel_button.setEnabled(False)
            self.summary_label.setText("Finishing the files already started...")

    def _on_progress(self, done: int, total: int, result) -> None:
        self.model.apply_result(result)
        self.builder.add(result)
        self.progress.setValue(done)
        self.summary_label.setText(f"Converting {done} of {total}...")
        if result.target is not None and self.last_output_folder is None:
            self.last_output_folder = result.target.parent

    def _on_completed(self, report) -> None:
        self._finish()
        self.summary_label.setText(report.summary())
        if report.converted and self.last_output_folder is None:
            target = report.converted[0].target
            if target is not None:
                self.last_output_folder = target.parent
        self.open_button.setEnabled(self.last_output_folder is not None)
        self.statusBar().showMessage(report.summary(), 10000)

    def _on_failed(self, message: str) -> None:
        self._finish()
        self.summary_label.setText("")
        QMessageBox.warning(self, APP_NAME, message)

    def _finish(self) -> None:
        self.progress.setVisible(False)
        self.cancel_button.setVisible(False)
        self.convert_button.setVisible(True)
        self.worker = None
        self._update_enabled()

    def open_output_folder(self) -> None:
        if self.last_output_folder is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_output_folder)))

    def closeEvent(self, event) -> None:  # noqa: N802
        """Stop a run cleanly rather than tearing a thread down mid-encode."""
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(5000)
        event.accept()
