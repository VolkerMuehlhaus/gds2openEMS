# -*- coding: utf-8 -*-
"""Optional window for convert2settings (``convert2settings --gui``).

Shows what the conversion changes before anything is written: a table of the variables
(converted with the proof, or kept with the reason) and the original and converted model side by
side, aligned row by row, with the changed lines and characters marked. Convert writes
<name>_settings.py next to the model, like the command line.

Modelled on EMStudio's "Convert to settings dictionary" dialog (src/convertloosemodel.cpp,
src/sidebysidediff.cpp). Needs PySide6, which is only imported when the window is used.
"""

import keyword
import os
import re
import sys

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QPainter, QPalette, QSyntaxHighlighter,
                           QTextCharFormat, QTextCursor, QTextFormat)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
                               QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QPlainTextEdit, QPushButton, QSplitter, QTableWidget,
                               QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from . import convert2settings as c2s

TITLE = "Convert to settings dictionary"

# Code panes: fixed light colours, background and text both set (Windows dark mode would
# otherwise give dark text on a dark background or the other way round)
PANE_BASE, PANE_TEXT = QColor("#ffffff"), QColor("#1f1f1f")
LINE_OLD, SPAN_OLD = QColor(220, 40, 40, 55), QColor(220, 40, 40, 120)
LINE_NEW, SPAN_NEW = QColor(30, 160, 30, 55), QColor(30, 160, 30, 120)
FILLER = QColor(128, 128, 128, 50)


class PythonHighlighter(QSyntaxHighlighter):
    """Keywords, strings, comments and numbers, enough to read a model script."""

    def __init__(self, document):
        super().__init__(document)

        def fmt(color, bold=False, italic=False):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(QFont.Bold)
            f.setFontItalic(italic)
            return f

        self.rules = [
            (re.compile(r"\b(%s)\b" % "|".join(keyword.kwlist)), fmt("#0000c0", bold=True)),
            (re.compile(r"\b(True|False|None)\b"), fmt("#0000c0", bold=True)),
            (re.compile(r"\b\d+(\.\d*)?([eE][+-]?\d+)?\b"), fmt("#a0522d")),
            (re.compile(r"""("[^"\\]*(\\.[^"\\]*)*"|'[^'\\]*(\\.[^'\\]*)*')"""), fmt("#008000")),
        ]
        self.comment = fmt("#808080", italic=True)

    def highlightBlock(self, text):
        for rx, f in self.rules:
            for m in rx.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), f)
        # a comment starts at the first # outside a string
        quote = None
        for i, ch in enumerate(text):
            if quote:
                if ch == quote:
                    quote = None
            elif ch in "'\"":
                quote = ch
            elif ch == "#":
                self.setFormat(i, len(text) - i, self.comment)
                break


class Gutter(QWidget):
    def __init__(self, pane):
        super().__init__(pane)
        self.pane = pane

    def sizeHint(self):
        return QSize(self.pane.gutter_width(), 0)

    def paintEvent(self, event):
        self.pane.paint_gutter(event)


class DiffPane(QPlainTextEdit):
    """Read-only code pane, one text block per row, with the source line numbers in a gutter
    (blank for filler rows)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        pal = self.palette()
        for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
            pal.setColor(group, QPalette.Base, PANE_BASE)
            pal.setColor(group, QPalette.Text, PANE_TEXT)
        self.setPalette(pal)
        PythonHighlighter(self.document())
        self.line_numbers = []
        self.gutter = Gutter(self)
        self.updateRequest.connect(self._update_gutter)
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def set_rows(self, texts, numbers):
        self.line_numbers = numbers
        self.setPlainText("\n".join(texts))
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)
        self.gutter.update()

    def gutter_width(self):
        digits = len(str(max(self.line_numbers or [1])))
        return 10 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_gutter(self, rect, dy):
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def paint_gutter(self, event):
        p = QPainter(self.gutter)
        p.fillRect(event.rect(), self.palette().color(QPalette.Window))
        p.setPen(self.palette().color(QPalette.Disabled, QPalette.Text))
        p.setFont(self.font())
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        while block.isValid() and top <= event.rect().bottom():
            height = round(self.blockBoundingRect(block).height())
            row = block.blockNumber()
            n = self.line_numbers[row] if row < len(self.line_numbers) else 0
            if block.isVisible() and n > 0 and top + height >= event.rect().top():
                p.drawText(0, top, self.gutter.width() - 5, height,
                           Qt.AlignRight | Qt.AlignVCenter, str(n))
            top += height
            block = block.next()
        p.end()


class SideBySideDiff(QWidget):
    """Original and converted model side by side, aligned by the converter's rows; scrolling is
    synchronized and Previous / Next jump between the changed blocks."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        nav = QHBoxLayout()
        legend = QLabel("<span style='background:#f4c7c7;color:#1f1f1f'>&nbsp;red&nbsp;</span> lines "
                        "that change, <span style='background:#c8ebc8;color:#1f1f1f'>&nbsp;green&nbsp;"
                        "</span> their new form (the changed part darker), <span style='background:"
                        "#dddddd;color:#1f1f1f'>&nbsp;grey&nbsp;</span> no matching line on that side")
        nav.addWidget(legend, 1)
        self.position = QLabel()
        self.prev = QPushButton("◀ Previous change")
        self.next = QPushButton("Next change ▶")
        nav.addWidget(self.position)
        nav.addWidget(self.prev)
        nav.addWidget(self.next)
        layout.addLayout(nav)

        split = QSplitter(Qt.Horizontal)
        self.titles, self.panes = [], []
        for _ in range(2):
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            title = QLabel()
            f = title.font()
            f.setBold(True)
            title.setFont(f)
            pane = DiffPane()
            v.addWidget(title)
            v.addWidget(pane, 1)
            split.addWidget(box)
            self.titles.append(title)
            self.panes.append(pane)
        layout.addWidget(split, 1)
        self.left, self.right = self.panes

        # both panes have the same rows, so equal scroll values show the same rows
        for a, b in ((self.left, self.right), (self.right, self.left)):
            a.verticalScrollBar().valueChanged.connect(b.verticalScrollBar().setValue)
            a.horizontalScrollBar().valueChanged.connect(b.horizontalScrollBar().setValue)
        self.prev.clicked.connect(lambda: self.go_to_change(self.current - 1))
        self.next.clicked.connect(lambda: self.go_to_change(self.current + 1))
        self.rows, self.change_starts, self.current = [], [], -1
        self._update_navigation()

    def set_content(self, left_lines, right_lines, rows, left_title, right_title):
        self.rows = rows
        self.titles[0].setText(left_title)
        self.titles[1].setText(right_title)
        lt = [left_lines[r["l"] - 1] if 0 < r["l"] <= len(left_lines) else "" for r in rows]
        rt = [right_lines[r["r"] - 1] if 0 < r["r"] <= len(right_lines) else "" for r in rows]
        self.left.set_rows(lt, [r["l"] for r in rows])
        self.right.set_rows(rt, [r["r"] for r in rows])
        self._apply_marks(self.left, True)
        self._apply_marks(self.right, False)
        self.change_starts = [i for i, r in enumerate(rows)
                              if r.get("c") and (i == 0 or not rows[i - 1].get("c"))]
        self.current = -1
        self._update_navigation()

    def clear(self):
        self.set_content([], [], [], "", "")

    def _apply_marks(self, pane, left):
        line_color, span_color = (LINE_OLD, SPAN_OLD) if left else (LINE_NEW, SPAN_NEW)
        marks = []
        block = pane.document().firstBlock()
        for r in self.rows:
            if not block.isValid():
                break
            line = r["l"] if left else r["r"]
            if line == 0 or r.get("c"):
                sel = QTextEdit.ExtraSelection()
                sel.format.setBackground(FILLER if line == 0 else line_color)
                sel.format.setProperty(QTextFormat.FullWidthSelection, True)
                sel.cursor = QTextCursor(block)
                marks.append(sel)
            for start, end in r.get("ls" if left else "rs", []):
                start = max(0, min(start, block.length() - 1))
                end = max(start, min(end, block.length() - 1))
                if end <= start:
                    continue
                sel = QTextEdit.ExtraSelection()
                sel.format.setBackground(span_color)
                sel.cursor = QTextCursor(block)
                sel.cursor.setPosition(block.position() + start)
                sel.cursor.setPosition(block.position() + end, QTextCursor.KeepAnchor)
                marks.append(sel)
            block = block.next()
        pane.setExtraSelections(marks)

    def go_to_change(self, index):
        if not self.change_starts:
            return
        self.current = max(0, min(index, len(self.change_starts) - 1))
        self._show_row(self.change_starts[self.current])
        self._update_navigation()

    def go_to_left_line(self, line):
        """Scrolls to an original line; when it is part of a change, that change becomes current."""
        row = next((i for i, r in enumerate(self.rows) if r["l"] == line), None)
        if row is None:
            return
        self._show_row(row)
        if self.rows[row].get("c"):
            self.current = max(c for c, start in enumerate(self.change_starts) if start <= row)
        self._update_navigation()

    def _show_row(self, row):
        block = self.left.document().findBlockByNumber(row)
        self.left.setTextCursor(QTextCursor(block))
        self.left.centerCursor()
        self.right.setTextCursor(QTextCursor(self.right.document().findBlockByNumber(row)))
        self.right.verticalScrollBar().setValue(self.left.verticalScrollBar().value())

    def _update_navigation(self):
        n = len(self.change_starts)
        self.prev.setEnabled(n > 0 and self.current > 0)
        self.next.setEnabled(n > 0 and self.current < n - 1)
        if n == 0:
            self.position.setText("No changes")
        elif self.current < 0:
            self.position.setText("%d change%s" % (n, "" if n == 1 else "s"))
        else:
            self.position.setText("Change %d of %d" % (self.current + 1, n))


class ConvertWindow(QDialog):
    """Model choice, GPU option, variable table, side-by-side preview, Convert."""

    def __init__(self, models, engine=None, package_dir=None, signatures=None):
        super().__init__()
        self.setWindowTitle(TITLE)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.package_dir, self.signatures = package_dir, signatures
        self.result = None          # (converter, new text, report) of the shown model

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Model:"))
        self.model_box = QComboBox()
        self.model_box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        top.addWidget(self.model_box, 1)
        open_button = QPushButton("Open model…")
        top.addWidget(open_button)
        self.gpu = QCheckBox("Run on the GPU (settings['engine'] = 'gpu')")
        self.gpu.setChecked(engine == "gpu")
        top.addWidget(self.gpu)
        layout.addLayout(top)

        self.intro = QLabel()
        self.intro.setWordWrap(True)
        layout.addWidget(self.intro)

        split = QSplitter(Qt.Vertical)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Variable", "Becomes", "Line", "Proven by / reason"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._row_clicked)
        self.diff = SideBySideDiff()
        split.addWidget(self.table)
        split.addWidget(self.diff)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 4)
        layout.addWidget(split, 1)

        buttons = QHBoxLayout()
        self.message = QLabel()
        self.message.setWordWrap(True)
        buttons.addWidget(self.message, 1)
        self.convert_button = QPushButton("Convert")
        self.convert_button.setDefault(True)
        close = QPushButton("Close")
        buttons.addWidget(self.convert_button)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        open_button.clicked.connect(self._open)
        self.model_box.currentIndexChanged.connect(lambda _: self.load())
        self.gpu.toggled.connect(lambda _: self.load())
        self.convert_button.clicked.connect(self._convert)
        close.clicked.connect(self.accept)

        for m in models:
            self.model_box.addItem(os.path.abspath(m))
        self.resize(1500, 1000)
        if models:
            self.load()

    def _open(self):
        start = os.path.dirname(self.model_box.currentText()) if self.model_box.count() else os.getcwd()
        files, _ = QFileDialog.getOpenFileNames(self, "Open model", start, "Python model (*.py)")
        for f in files:
            f = os.path.abspath(f)
            if self.model_box.findText(f) < 0:
                self.model_box.addItem(f)
        if files:
            self.model_box.setCurrentIndex(self.model_box.findText(os.path.abspath(files[0])))

    def load(self):
        """Converts the selected model in memory and shows the result."""
        model = self.model_box.currentText()
        self.result = None
        self.table.setRowCount(0)
        self.diff.clear()
        self.convert_button.setEnabled(False)
        self.message.setText("")
        if not model:
            self.intro.setText("Open a model script in the older loose-variable syntax.")
            return
        engine = "gpu" if self.gpu.isChecked() else None
        try:
            self.result = c2s.convert(model, engine, self.package_dir, self.signatures)
        except (c2s.Refused, OSError, UnicodeDecodeError) as e:
            self.intro.setText("<b style='color:#c00000'>This model can't be converted.</b> "
                               "Nothing is written.<br><br>%s" % _html(str(e)))
            return
        _, _, report = self.result
        out = c2s.output_path(model)
        switch = ""
        if report["needs_import_switch"]:
            switch = (" The imports of the local <b>modules</b> folder are switched to the installed "
                      "<b>gds2openEMS</b>%s, so the converted model uses the current workflow." %
                      (", and the sys.path line for that folder is removed"
                       if report["removed_syspath_lines"] else ""))
        self.intro.setText(
            "Each variable below becomes <b>settings['key']</b> because of how the model uses it "
            "(the <i>Proven by</i> column); nothing is guessed from names. setupSimulation() and "
            "runSimulation() are called with <b>settings=settings</b>, like the current gds2openEMS "
            "examples.%s The conversion was verified to give exactly the intended code.<br><br>"
            "Convert writes <b>%s</b> next to the model. The model itself is not changed."
            % (switch, _html(os.path.basename(out))))

        rows = [(c["name"], "settings['%s']" % c["key"], c["line"], c["proof"])
                for c in report["converted"]]
        rows += [(c["name"], "stays a variable", c["line"], c["reason"]) for c in report["loose"]]
        rows.sort(key=lambda r: r[2])
        self.table.setRowCount(len(rows))
        for i, (name, becomes, line, why) in enumerate(rows):
            for col, value in enumerate((name, becomes, str(line), why)):
                item = QTableWidgetItem(value)
                if col == 3:
                    item.setToolTip(why)
                self.table.setItem(i, col, item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)

        self.diff.set_content(report["original_lines"], report["converted_lines"], report["rows"],
                              "Original: %s" % os.path.basename(model),
                              "Converted: %s" % os.path.basename(out))
        self.diff.go_to_change(0)
        if os.path.exists(out):
            self.message.setText("<span style='color:#c00000'>%s already exists and is not "
                                 "overwritten. Rename or delete it to convert again.</span>"
                                 % _html(os.path.basename(out)))
        else:
            self.convert_button.setEnabled(True)

    def _row_clicked(self, row, _col):
        item = self.table.item(row, 2)
        if item:
            self.diff.go_to_left_line(int(item.text()))

    def _convert(self):
        if not self.result:
            return
        conv, new_text, _ = self.result
        out = c2s.output_path(conv.model_path)
        try:
            with open(out, "xb") as f:
                f.write(conv.src.encode(new_text))
        except OSError as e:
            QMessageBox.warning(self, TITLE, "Not written: %s" % e)
            return
        self.convert_button.setEnabled(False)
        self.message.setText("Written: %s" % _html(out))
        QMessageBox.information(self, TITLE, "The converted model was written to\n\n%s\n\n"
                                             "Check it in the AppCSXCAD preview before the first run." % out)


def _html(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def run(models, engine=None, package_dir=None, signatures=None):
    """Opens the window; with no model, asks for one first. Returns the exit code."""
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = ConvertWindow(models, engine, package_dir, signatures)
    if not models:
        window.show()
        window._open()
    window.exec()
    return 0
