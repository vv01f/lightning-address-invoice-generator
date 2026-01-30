#!/usr/bin/env python3
"""
PySide6 GUI wrapper for lnaddress2invoice.py

Place this file next to your existing `lnaddress2invoice.py` (the script you supplied).
Run with: python lnaddress2invoice_gui.py

This GUI provides:
 - Recipient (Lightning Address) input
 - Amount (integer, sats) input
 - Paste button: pastes clipboard if it *looks like* an lnaddress
 - Generate button: calls get_bolt11(lnaddress, amount) in a background thread
 - Read-only invoice field with Copy button. Double-clicking the invoice field also copies it.
 - Status line for errors / progress

Requires: PySide6, requests (already used by the script)
"""

from __future__ import annotations
import sys
import re
from typing import Optional
from PySide6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QLabel, QLineEdit, QPushButton,
    QHBoxLayout, QVBoxLayout, QMessageBox, QSizePolicy
)
from PySide6.QtGui import QRegularExpressionValidator, QClipboard, QPixmap, QMouseEvent, Qt
from PySide6.QtCore import QRegularExpression, QObject, Signal, QThread, QPoint
import json

import qrcode
from qrcode.image.pil import PilImage  # important!
from PIL.ImageQt import ImageQt

# Import the get_bolt11 function from the existing script
# Make sure lnaddress2invoice.py is in the same directory or in PYTHONPATH
try:
    from lnaddress2invoice import get_bolt11
except Exception as e:
    get_bolt11 = None

LNADDRESS_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ScalableQRCodeLabel(QLabel):
    """
    QLabel that shows a QR code pixmap.
    - Pixmap scales to label size
    - Mouse wheel scales the QR code
    - Double-click copies pixmap to clipboard
    """
    def __init__(self, parent=None, status_callback=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Remove fixed size
        # self.setFixedSize(150, 150)
        self._pixmap_orig: QPixmap | None = None
        self._scale = 1.0
        self.status_callback = status_callback

    def setPixmap(self, pixmap: QPixmap):
        """Store original pixmap and apply current scale."""
        self._pixmap_orig = pixmap
        self._scale = 1.0
        self._update_pixmap()

    def _update_pixmap(self):
        if self._pixmap_orig:
            w = int(self.width() * self._scale)
            h = int(self.height() * self._scale)
            scaled = self._pixmap_orig.scaled(
                w,
                h,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            super().setPixmap(scaled)

    def resizeEvent(self, event):
        self._update_pixmap()
        super().resizeEvent(event)

    # ~ def wheelEvent(self, event):
        # ~ if self._pixmap_orig:
            # ~ delta = event.angleDelta().y()
            # ~ factor = 1.1 if delta > 0 else 0.9
            # ~ self._scale *= factor
            # ~ self._scale = max(0.1, min(self._scale, 5.0))
            # ~ self._update_pixmap()

    def mouseDoubleClickEvent(self, event):
        if self.pixmap():
            QApplication.clipboard().setPixmap(self.pixmap())
            if self.status_callback:
                self.status_callback("QR copied to clipboard.")


def generate_invoice_qr(invoice_text: str) -> QPixmap:
    """
    Generate a QR code from a BOLT11 invoice and return a QPixmap to display in PySide6.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(invoice_text)
    qr.make(fit=True)

    # generate a PIL image (not BaseImage)
    img: PilImage = qr.make_image(fill_color="black", back_color="white", image_factory=PilImage)
    pil_image = img.get_image()  # PilImage wrapper -> actual PIL.Image.Image

    qt_image = ImageQt(pil_image)  # now it works
    pixmap = QPixmap.fromImage(qt_image)
    return pixmap


class ClickCopyLineEdit(QLineEdit):
    """Read-only QLineEdit that copies its contents to the clipboard on double-click."""
    def mouseDoubleClickEvent(self, ev):
        text = self.text()
        if text:
            cb = QApplication.clipboard()
            cb.setText(text, mode=QClipboard.Clipboard)
        super().mouseDoubleClickEvent(ev)


class InvoiceWorker(QObject):
    finished = Signal(dict)

    def __init__(self, lnaddress: str, amount: int, comment: str = None):
        super().__init__()
        self.lnaddress = lnaddress
        self.amount = amount
        self.comment = comment

    def run(self):
        """Call get_bolt11 and emit result. Runs in another thread."""
        if get_bolt11 is None:
            self.finished.emit({"status": "error", "msg": "Could not import get_bolt11 from lnaddress2invoice.py"})
            return
        try:
            res = get_bolt11(self.lnaddress, self.amount, self.comment)
            # Ensure a dict
            if not isinstance(res, dict):
                res = {"status": "error", "msg": "Unexpected non-dict response from get_bolt11"}
        except Exception as e:
            res = {"status": "error", "msg": str(e)}
        self.finished.emit(res)


class RecipientLineEdit(QLineEdit):
    """
    Subclass QLineEdit to move focus to Amount field when LNAddress editing is done.
    """
    def __init__(self, main_window: MainWindow):
        super().__init__()
        self.main_window = main_window

    def focusOutEvent(self, event):
        # Call the main window handler first
        self.main_window.on_lnaddress_finished()
        # Force focus to Amount field
        self.main_window.edit_amount.setFocus()
        # Continue with normal focus-out handling
        super().focusOutEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LNAddress → BOLT11")
        self.resize(400, 320)
        self.setMinimumSize(320,250)

        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout()

        # Recipient row
        row_recipient = QHBoxLayout()
        lbl_recipient = QLabel("Recipient (lnaddress):")
        # ~ self.edit_recipient = QLineEdit()
        # ~ self.edit_recipient.editingFinished.connect(self.on_lnaddress_finished)
        self.edit_recipient = RecipientLineEdit(self)
        self.edit_recipient.setPlaceholderText("user@example.com")
        btn_paste = QPushButton("Paste"
        )
        btn_paste.clicked.connect(self.on_paste)

        row_recipient.addWidget(lbl_recipient)
        row_recipient.addWidget(self.edit_recipient)
        row_recipient.addWidget(btn_paste)

        # Amount row
        row_amount = QHBoxLayout()
        lbl_amount = QLabel("Amount (sats):")
        self.edit_amount = QLineEdit()
        self.edit_amount.setValidator(QRegularExpressionValidator(QRegularExpression(r"^[0-9]{1,18}$"), self))
        self.edit_amount.setPlaceholderText("e.g. 1000")
        row_amount.addWidget(lbl_amount)
        row_amount.addWidget(self.edit_amount)

        # --- Kommentar row ---
        row_comment = QHBoxLayout()
        lbl_comment = QLabel("Description:")

        # Textfeld für Kommentar
        self.edit_comment = QLineEdit()
        self.edit_comment.setPlaceholderText("Optionaler Kommentar...")

        # Label für verbleibende Zeichen
        self.lbl_comment_remaining = QLabel("0 Zeichen übrig")  # Initialwert

        row_comment.addWidget(lbl_comment)
        row_comment.addWidget(self.edit_comment)
        row_comment.addWidget(self.lbl_comment_remaining)

        # Generate button
        self.btn_generate = QPushButton("Generate Invoice")
        self.btn_generate.clicked.connect(self.on_generate)
        self.btn_generate.setDefault(True)

        # Invoice output row
        row_invoice = QHBoxLayout()
        lbl_invoice = QLabel("BOLT11 Invoice:")
        self.edit_invoice = ClickCopyLineEdit()
        self.edit_invoice.setReadOnly(True)
        self.edit_invoice.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        btn_copy = QPushButton("Copy")
        btn_copy.clicked.connect(self.on_copy_invoice)

        row_invoice.addWidget(lbl_invoice)
        row_invoice.addWidget(self.edit_invoice)
        row_invoice.addWidget(btn_copy)

        # QR code
        self.lbl_qr = ScalableQRCodeLabel(status_callback=self.update_status)
        self.qr_container = QWidget()
        qr_layout = QVBoxLayout(self.qr_container)
        qr_layout.setContentsMargins(0, 0, 0, 0)
        qr_layout.addWidget(self.lbl_qr)
        self.qr_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Status label
        self.lbl_status = QLabel("")

        layout.addLayout(row_recipient)
        layout.addLayout(row_amount)
        layout.addLayout(row_comment)
        layout.addWidget(self.btn_generate)
        layout.addLayout(row_invoice)
        layout.addWidget(self.qr_container)
        layout.addWidget(self.lbl_status)

        central.setLayout(layout)

        # Thread placeholders
        self._thread: Optional[QThread] = None
        self._worker: Optional[InvoiceWorker] = None

    def update_status(self, msg: str):
        self.lbl_status.setText(msg)

    def on_lnaddress_finished(self):
        """
        Wird aufgerufen, wenn der Nutzer das LN-Address-Feld verlässt.
        Ruft die PayURL ab und liest die maximale Kommentar-Länge aus.
        """
        lnaddress = self.edit_recipient.text().strip()
        if not lnaddress:
            return  # leer, nichts tun

        # Optional: nur wenn es wie eine lnaddress aussieht
        if not LNADDRESS_RE.match(lnaddress):
            self.lbl_status.setText("LNAddress scheint ungültig, Kommentar-Max-Länge nicht gesetzt.")
            return

        try:
            # PayURL abrufen
            from lnaddress2invoice import get_payurl, get_url, get_comment_length
            purl = get_payurl(lnaddress)
            json_content = get_url(purl, headers={}).strip()
            datablock = json.loads(json_content)
            comment_allowed = get_comment_length(datablock)

            # Setze max Länge im GUI
            self.set_comment_max_length(comment_allowed)
            self.lbl_status.setText(f"Maximale Kommentar-Länge: {comment_allowed} Zeichen.")

        except Exception as e:
            self.lbl_status.setText(f"Fehler beim Abrufen der Kommentar-Länge: {str(e)}")

    def set_comment_max_length(self, max_len: int):
        """Set maximum allowed comment length and connect live counter."""
        self.comment_max_len = max_len
        self.edit_comment.textChanged.connect(self.update_comment_remaining)
        self.update_comment_remaining()  # initial update

    def update_comment_remaining(self):
        """Update remaining characters label and truncate if necessary."""
        text = self.edit_comment.text()
        if hasattr(self, "comment_max_len"):
            if len(text) > self.comment_max_len:
                # automatisch kürzen
                self.edit_comment.setText(text[:self.comment_max_len])
                text = self.edit_comment.text()
            remaining = self.comment_max_len - len(text)
            self.lbl_comment_remaining.setText(f"{remaining} Zeichen übrig")
        else:
            # fallback
            self.lbl_comment_remaining.setText("0 Zeichen übrig")

    def on_paste(self):
        cb = QApplication.clipboard()
        text = cb.text().strip()
        if LNADDRESS_RE.match(text):
            self.edit_recipient.setText(text)
            self.lbl_status.setText("Pasted lnaddress from clipboard.")
        else:
            # Not an lnaddress: ask the user whether to paste anyway
            ret = QMessageBox.question(self, "Paste from clipboard?",
                                       "Clipboard does not look like an lnaddress. Paste anyway?",
                                       QMessageBox.Yes | QMessageBox.No)
            if ret == QMessageBox.Yes:
                self.edit_recipient.setText(text)
                self.lbl_status.setText("Pasted clipboard (didn't match lnaddress pattern).")

    def on_generate(self):
        lnaddress = self.edit_recipient.text().strip()
        amount_text = self.edit_amount.text().strip()

        if not lnaddress:
            QMessageBox.warning(self, "Missing recipient", "Please enter the recipient Lightning Address.")
            return
        if not LNADDRESS_RE.match(lnaddress):
            resp = QMessageBox.question(self, "Recipient format",
                                        "Recipient doesn't look like an lnaddress. Continue anyway?",
                                        QMessageBox.Yes | QMessageBox.No)
            if resp != QMessageBox.Yes:
                return

        if not amount_text:
            QMessageBox.warning(self, "Missing amount", "Please enter an amount (integer sats).")
            return

        try:
            amount = int(amount_text)
            if amount < 0:
                raise ValueError("Amount negative")
        except Exception:
            QMessageBox.warning(self, "Invalid amount", "Amount must be a non-negative integer (satoshis).")
            return

        comment = self.edit_comment.text().strip() or None

        # Disable UI while working
        self.btn_generate.setEnabled(False)
        self.lbl_status.setText("Generating invoice...")
        self.edit_invoice.clear()

        # Create worker and thread
        self._thread = QThread()
        self._worker = InvoiceWorker(lnaddress, amount, comment)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self.on_worker_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def on_worker_finished(self, result: dict):
        self.btn_generate.setEnabled(True)

        if result.get("status") == "ok":
            bolt11 = result.get("bolt11")
            self.edit_invoice.setText(bolt11)
            self.edit_invoice.selectAll()  # select the text
            self.edit_invoice.setFocus()   # optional: move focus
            self.lbl_status.setText("Invoice generated successfully. Double-click or press Copy to copy to clipboard.")
            # Generate QR code
            # QR generieren
            pixmap = generate_invoice_qr(bolt11)
            # Pixmap auf Label setzen, Label passt sich an
            self.lbl_qr.setPixmap(pixmap)
            self.lbl_status.setText("Invoice and QR generated successfully. Double-click to copy to clipboard.")
        else:
            msg = result.get("msg", "Unknown error")
            self.lbl_status.setText(f"Error: {msg}")
            self.lbl_qr.clear()  # QR leeren, falls vorher erzeugt
            QMessageBox.critical(self, "Error", str(msg))

    def on_copy_invoice(self):
        text = self.edit_invoice.text()
        if not text:
            QMessageBox.information(self, "Nothing to copy", "There is no invoice to copy.")
            return
        cb = QApplication.clipboard()
        cb.setText(text, mode=QClipboard.Clipboard)
        self.lbl_status.setText("Invoice copied to clipboard.")


def main():
    app = QApplication(sys.argv)

    if get_bolt11 is None:
        QMessageBox.critical(None, "Import Error",
                             "Could not import get_bolt11 from lnaddress2invoice.py.\n"
                             "Make sure lnaddress2invoice.py is in the same directory and is importable.")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
