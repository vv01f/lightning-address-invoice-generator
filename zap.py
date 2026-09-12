#!/usr/bin/env python3
"""
PySide6 GUI wrapper for lnaddress2invoice.py

Place this file next to:
    lnaddress2invoice.py

Run with:
    python lnaddress2invoice_gui.py

Supported recipients:
 - Lightning Address
 - LNURL
 - Nostr npub
 - Nostr nprofile

The GUI uses get_bolt11() from lnaddress2invoice.py as the authoritative
invoice-generation implementation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Optional

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QMainWindow,
    QLabel,
    QLineEdit,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QMessageBox,
    QSizePolicy,
)
from PySide6.QtGui import (
    QRegularExpressionValidator,
    QClipboard,
    QPixmap,
    Qt,
)
from PySide6.QtCore import (
    QRegularExpression,
    QObject,
    Signal,
    QThread,
)

import qrcode
from qrcode.image.pil import PilImage
from PIL.ImageQt import ImageQt


# ---------------------------------------------------------------------------
# Import CLI functions
# ---------------------------------------------------------------------------

try:
    from lnaddress2invoice import (
        get_bolt11,
        is_lnurl,
        is_nostr_profile,
        normalize_lightning_uri,
        normalize_nostr_uri,
    )
except Exception:
    get_bolt11 = None
    is_lnurl = None
    is_nostr_profile = None
    normalize_lightning_uri = None
    normalize_nostr_uri = None


LNADDRESS_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------------------
# Recipient helpers
# ---------------------------------------------------------------------------

def normalize_recipient(value: str) -> str:
    """
    Remove supported URI prefixes.

    Supported:
        lightning:user@example.com
        nostr:npub1...
        nostr:nprofile1...
    """
    value = value.strip()

    if value.lower().startswith("lightning:"):
        return value[len("lightning:"):].strip()

    if value.lower().startswith("nostr:"):
        return value[len("nostr:"):].strip()

    return value


def is_supported_recipient(value: str) -> bool:
    """
    Return True for:
      - Lightning Address
      - LNURL
      - npub
      - nprofile
    """
    value = normalize_recipient(value)

    if not value:
        return False

    if LNADDRESS_RE.match(value):
        return True

    if is_lnurl is not None and is_lnurl(value):
        return True

    if is_nostr_profile is not None and is_nostr_profile(value):
        return True

    return False


# ---------------------------------------------------------------------------
# LNURL / recipient lookup worker
# ---------------------------------------------------------------------------

class LNURLWorker(QObject):
    finished = Signal(dict)

    def __init__(self, recipient: str):
        super().__init__()
        self.recipient = recipient

    def run(self):
        try:
            from lnaddress2invoice import (
                get_payurl,
                get_url,
                get_comment_length,
                get_metadata_identifier,
                is_lnurl,
                decode_lnurl,
                derive_lnaddress_from_url,
                resolve_recipient,
            )

            recipient = self.recipient.strip()

            # ---------------------------------------------------------
            # First resolve the recipient exactly as the CLI does.
            # ---------------------------------------------------------
            resolved_recipient, source_type = resolve_recipient(
                recipient
            )

            # ---------------------------------------------------------
            # Nostr profile:
            #
            # resolve_recipient() has already resolved:
            #
            #   npub/nprofile
            #       -> lud16 or lud06
            #
            # Continue with that resolved Lightning recipient.
            # ---------------------------------------------------------
            if source_type == "nostr":
                lookup_recipient = resolved_recipient
            else:
                lookup_recipient = recipient

            # ---------------------------------------------------------
            # Resolve LNURL / Lightning Address to pay URL.
            # ---------------------------------------------------------
            if is_lnurl(lookup_recipient):
                purl = decode_lnurl(lookup_recipient)
            else:
                purl = get_payurl(lookup_recipient)

            # ---------------------------------------------------------
            # Fetch payRequest.
            # ---------------------------------------------------------
            try:
                json_content = get_url(
                    purl,
                    headers={},
                ).strip()
            except Exception as e:
                raise ValueError(
                    "Server not reachable or address does not exist"
                ) from e

            try:
                datablock = json.loads(json_content)
            except Exception as e:
                raise ValueError(
                    "Server returned an invalid response"
                ) from e

            if datablock.get("tag") != "payRequest":
                raise ValueError(
                    "Not a pay-request LNURL "
                    f"(tag: {datablock.get('tag')})"
                )

            # ---------------------------------------------------------
            # Determine effective Lightning Address.
            # ---------------------------------------------------------
            effective_lnaddress = (
                get_metadata_identifier(datablock)
                or derive_lnaddress_from_url(
                    datablock.get("callback", "")
                )
                or (
                    resolved_recipient
                    if not is_lnurl(resolved_recipient)
                    else None
                )
            )

            comment_allowed = get_comment_length(datablock)

            self.finished.emit(
                {
                    "status": "ok",
                    "comment_length": comment_allowed,
                    "effective_lnaddress": effective_lnaddress,
                    "source_type": source_type,
                    "resolved_recipient": resolved_recipient,
                }
            )

        except Exception as e:
            # Do NOT hide the actual error. This is important for
            # diagnosing Nostr/relay problems.
            self.finished.emit(
                {
                    "status": "error",
                    "msg": f"{type(e).__name__}: {e}",
                }
            )


# ---------------------------------------------------------------------------
# QR code widget
# ---------------------------------------------------------------------------

class ScalableQRCodeLabel(QLabel):
    """
    QLabel that shows a QR code pixmap.

    - Pixmap scales to label size.
    - Double-click copies the QR image to clipboard.
    """

    def __init__(self, parent=None, status_callback=None):
        super().__init__(parent)

        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Expanding,
        )

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
            w = max(1, int(self.width() * self._scale))
            h = max(1, int(self.height() * self._scale))

            scaled = self._pixmap_orig.scaled(
                w,
                h,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )

            super().setPixmap(scaled)

    def resizeEvent(self, event):
        self._update_pixmap()
        super().resizeEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.pixmap():
            QApplication.clipboard().setPixmap(self.pixmap())

            if self.status_callback:
                self.status_callback(
                    "QR copied to clipboard."
                )

        super().mouseDoubleClickEvent(event)


# ---------------------------------------------------------------------------
# QR generation
# ---------------------------------------------------------------------------

def generate_invoice_qr(invoice_text: str) -> QPixmap:
    """Generate a QR code from a BOLT11 invoice."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )

    qr.add_data(invoice_text)
    qr.make(fit=True)

    img: PilImage = qr.make_image(
        fill_color="black",
        back_color="white",
        image_factory=PilImage,
    )

    pil_image = img.get_image()
    qt_image = ImageQt(pil_image)

    return QPixmap.fromImage(qt_image)


# ---------------------------------------------------------------------------
# Invoice field
# ---------------------------------------------------------------------------

class ClickCopyLineEdit(QLineEdit):
    """Read-only QLineEdit that copies its contents on double-click."""

    def mouseDoubleClickEvent(self, ev):
        text = self.text()

        if text:
            QApplication.clipboard().setText(
                text,
                mode=QClipboard.Clipboard,
            )

        super().mouseDoubleClickEvent(ev)


# ---------------------------------------------------------------------------
# Invoice worker
# ---------------------------------------------------------------------------

class InvoiceWorker(QObject):
    finished = Signal(dict)

    def __init__(
        self,
        recipient: str,
        amount: int,
        comment: str | None = None,
    ):
        super().__init__()

        self.recipient = recipient
        self.amount = amount
        self.comment = comment

    def run(self):
        """Call get_bolt11() and emit the result."""
        if get_bolt11 is None:
            self.finished.emit(
                {
                    "status": "error",
                    "msg": (
                        "Could not import get_bolt11 from "
                        "lnaddress2invoice.py"
                    ),
                }
            )
            return

        try:
            # Keep get_bolt11() authoritative.
            #
            # This deliberately passes the original recipient, which may
            # be an npub/nprofile. The CLI implementation performs the
            # Nostr resolution itself.
            res = get_bolt11(
                self.recipient,
                self.amount,
                self.comment,
            )

            if not isinstance(res, dict):
                res = {
                    "status": "error",
                    "msg": (
                        "Unexpected non-dict response "
                        "from get_bolt11"
                    ),
                }

        except Exception as e:
            res = {
                "status": "error",
                "msg": str(e),
            }

        self.finished.emit(res)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("LNAddress to BOLT11")
        self.resize(400, 320)
        self.setMinimumSize(320, 250)

        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout()

        # ---------------------------------------------------------------
        # Recipient
        # ---------------------------------------------------------------

        row_recipient = QHBoxLayout()

        lbl_recipient = QLabel("Recipient:")

        self.edit_recipient = QLineEdit(self)
        self.edit_recipient.setPlaceholderText(
            "username@domain.tld, LNURL…, npub1…, or nprofile1…"
        )
        self.edit_recipient.editingFinished.connect(
            self.on_lnaddress_finished
        )

        btn_paste = QPushButton("Paste")
        btn_paste.clicked.connect(self.on_paste)

        row_recipient.addWidget(lbl_recipient)
        row_recipient.addWidget(self.edit_recipient)
        row_recipient.addWidget(btn_paste)

        # ---------------------------------------------------------------
        # Effective LNAddress
        # ---------------------------------------------------------------

        row_effective = QHBoxLayout()

        lbl_effective = QLabel("Effective LNAddress:")

        self.edit_effective = QLineEdit()
        self.edit_effective.setReadOnly(True)
        self.edit_effective.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Preferred,
        )

        row_effective.addWidget(lbl_effective)
        row_effective.addWidget(self.edit_effective)

        # ---------------------------------------------------------------
        # Amount
        # ---------------------------------------------------------------

        row_amount = QHBoxLayout()

        lbl_amount = QLabel("Amount (sats):")

        self.edit_amount = QLineEdit()

        self.edit_amount.setValidator(
            QRegularExpressionValidator(
                QRegularExpression(r"^[0-9]{1,18}$"),
                self,
            )
        )

        self.edit_amount.setPlaceholderText("e.g. 1000")

        row_amount.addWidget(lbl_amount)
        row_amount.addWidget(self.edit_amount)

        # ---------------------------------------------------------------
        # Description
        # ---------------------------------------------------------------

        row_comment = QHBoxLayout()

        lbl_comment = QLabel("Description:")

        self.edit_comment = QLineEdit()
        self.edit_comment.setPlaceholderText(
            "Optional Description..."
        )

        self._comment_signal_connected = False
        self.comment_max_len = 0

        self.lbl_comment_remaining = QLabel(
            "0 characters left"
        )

        row_comment.addWidget(lbl_comment)
        row_comment.addWidget(self.edit_comment)
        row_comment.addWidget(
            self.lbl_comment_remaining
        )

        # ---------------------------------------------------------------
        # Generate
        # ---------------------------------------------------------------

        self.btn_generate = QPushButton(
            "Generate Invoice"
        )

        self.btn_generate.clicked.connect(
            self.on_generate
        )

        self.btn_generate.setDefault(True)

        # ---------------------------------------------------------------
        # Invoice
        # ---------------------------------------------------------------

        row_invoice = QHBoxLayout()

        lbl_invoice = QLabel("BOLT11 Invoice:")

        self.edit_invoice = ClickCopyLineEdit()
        self.edit_invoice.setReadOnly(True)
        self.edit_invoice.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Preferred,
        )

        btn_copy = QPushButton("Copy")
        btn_copy.clicked.connect(
            self.on_copy_invoice
        )

        row_invoice.addWidget(lbl_invoice)
        row_invoice.addWidget(self.edit_invoice)
        row_invoice.addWidget(btn_copy)

        # ---------------------------------------------------------------
        # QR
        # ---------------------------------------------------------------

        self.lbl_qr = ScalableQRCodeLabel(
            status_callback=self.update_status
        )

        self.qr_container = QWidget()

        qr_layout = QVBoxLayout(
            self.qr_container
        )

        qr_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        qr_layout.addWidget(self.lbl_qr)

        self.qr_container.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Expanding,
        )

        # ---------------------------------------------------------------
        # Status
        # ---------------------------------------------------------------

        self.lbl_status = QLabel("")

        # ---------------------------------------------------------------
        # Main layout
        # ---------------------------------------------------------------

        layout.addLayout(row_recipient)
        layout.addLayout(row_effective)
        layout.addLayout(row_amount)
        layout.addLayout(row_comment)
        layout.addWidget(self.btn_generate)
        layout.addLayout(row_invoice)
        layout.addWidget(self.qr_container)
        layout.addWidget(self.lbl_status)

        central.setLayout(layout)

        # ---------------------------------------------------------------
        # Thread state
        # ---------------------------------------------------------------

        self._thread: Optional[QThread] = None
        self._worker: Optional[InvoiceWorker] = None

        self._lnurl_thread: Optional[QThread] = None
        self._lnurl_worker: Optional[LNURLWorker] = None

    # -------------------------------------------------------------------
    # Status
    # -------------------------------------------------------------------

    def update_status(self, msg: str):
        self.lbl_status.setText(msg)

    # -------------------------------------------------------------------
    # LNURL worker cleanup
    # -------------------------------------------------------------------

    def _clear_lnurl_thread(self):
        """
        Forget the LNURL worker/thread after Qt has finished them.
        """
        self._lnurl_worker = None
        self._lnurl_thread = None

    # -------------------------------------------------------------------
    # Recipient validation / resolution
    # -------------------------------------------------------------------

    def on_lnaddress_finished(self):
        if self._lnurl_thread is not None:
            try:
                if self._lnurl_thread.isRunning():
                    return
            except RuntimeError:
                self._lnurl_thread = None
                self._lnurl_worker = None
    
        self.edit_effective.clear()
        self.edit_amount.setFocus()
    
        raw_recipient = self.edit_recipient.text().strip()
        recipient = normalize_recipient(raw_recipient)
    
        if recipient != raw_recipient:
            self.edit_recipient.setText(recipient)
    
        if not recipient:
            return
    
        if not is_supported_recipient(recipient):
            self.lbl_status.setText(
                "Recipient is not a valid Lightning Address, "
                "LNURL, npub, or nprofile."
            )
            self.set_comment_max_length(0)
            return
    
        self.edit_recipient.setEnabled(False)
        self.lbl_comment_remaining.setText("0 characters left")
        self.lbl_status.setText("Resolving recipient...")
    
        thread = QThread(self)
        worker = LNURLWorker(recipient)
    
        self._lnurl_thread = thread
        self._lnurl_worker = worker
    
        worker.moveToThread(thread)
    
        thread.started.connect(worker.run)
    
        worker.finished.connect(self.on_lnurl_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
    
        thread.finished.connect(self._clear_lnurl_thread)
        thread.finished.connect(thread.deleteLater)
    
        thread.start()

    # -------------------------------------------------------------------
    # LNURL worker result
    # -------------------------------------------------------------------

    def on_lnurl_finished(self, result: dict):
        self.edit_recipient.setEnabled(True)
    
        if result.get("status") == "ok":
            max_len = result.get("comment_length", 0)
            effective = result.get("effective_lnaddress")
            source_type = result.get("source_type")
    
            self.edit_effective.setText(effective or "")
            self.set_comment_max_length(max_len)
    
            if source_type == "nostr":
                if effective:
                    self.lbl_status.setText(
                        f"Nostr profile resolved. "
                        f"Desc. limit: {max_len} characters. "
                        f"Eff. LNAddress: {effective}"
                    )
                else:
                    self.lbl_status.setText(
                        f"Nostr profile resolved. "
                        f"Desc. limit: {max_len} characters."
                    )
            elif effective:
                self.lbl_status.setText(
                    f"Desc. limit: {max_len} characters. "
                    f"Eff. LNAddress: {effective}"
                )
            else:
                self.lbl_status.setText(
                    f"Description length limit: {max_len} characters. "
                    "No effective LNAddress derivable."
                )
    
        else:
            msg = result.get("msg", "Unknown error")
    
            self.edit_effective.clear()
            self.set_comment_max_length(0)
    
            self.lbl_status.setText(
                f"Recipient resolution failed: {msg}"
            )

    # -------------------------------------------------------------------
    # Comment handling
    # -------------------------------------------------------------------

    def set_comment_max_length(self, max_len: int):
        """Set maximum allowed comment length."""
        self.comment_max_len = max_len

        if self._comment_signal_connected:
            try:
                self.edit_comment.textChanged.disconnect(
                    self.update_comment_remaining
                )
            except (RuntimeError, TypeError):
                pass

            self._comment_signal_connected = False

        if max_len == 0:
            self.edit_comment.clear()
            self.edit_comment.setEnabled(False)
            self.edit_comment.setPlaceholderText(
                "Description disallowed..."
            )
            self.lbl_comment_remaining.setText(
                "Zero"
            )

        else:
            self.edit_comment.setEnabled(True)

            self.edit_comment.setPlaceholderText(
                "Optional Description..."
            )

            self.edit_comment.textChanged.connect(
                self.update_comment_remaining
            )

            self._comment_signal_connected = True

            self.update_comment_remaining()

    def update_comment_remaining(self):
        """Update remaining characters and truncate if necessary."""
        text = self.edit_comment.text()

        if hasattr(self, "comment_max_len"):
            if len(text) > self.comment_max_len:
                self.edit_comment.setText(
                    text[:self.comment_max_len]
                )
                text = self.edit_comment.text()

            remaining = (
                self.comment_max_len
                - len(text)
            )

            self.lbl_comment_remaining.setText(
                f"{remaining} characters left"
            )

        else:
            self.lbl_comment_remaining.setText(
                "0 characters left"
            )

    # -------------------------------------------------------------------
    # Paste
    # -------------------------------------------------------------------

    def on_paste(self):
        cb = QApplication.clipboard()
        text = cb.text().strip()

        if is_supported_recipient(text):
            self.edit_recipient.setText(text)

            self.lbl_status.setText(
                "Pasted supported recipient from clipboard."
            )

            self.on_lnaddress_finished()

            return

        ret = QMessageBox.question(
            self,
            "Paste from clipboard?",
            "Clipboard does not look like a Lightning Address, "
            "LNURL, npub, or nprofile. Paste anyway?",
            QMessageBox.Yes | QMessageBox.No,
        )

        if ret == QMessageBox.Yes:
            self.edit_recipient.setText(text)

            self.lbl_status.setText(
                "Pasted clipboard "
                "(didn't match a supported recipient format)."
            )

            self.on_lnaddress_finished()

    # -------------------------------------------------------------------
    # Generate invoice
    # -------------------------------------------------------------------

    def on_generate(self):
        raw_recipient = self.edit_recipient.text()

        recipient = normalize_recipient(
            raw_recipient
        )

        if recipient != raw_recipient.strip():
            self.edit_recipient.setText(
                recipient
            )

        amount_text = (
            self.edit_amount.text().strip()
        )

        if not recipient:
            QMessageBox.warning(
                self,
                "Missing recipient",
                "Please enter a recipient.",
            )
            return

        if not is_supported_recipient(recipient):
            resp = QMessageBox.question(
                self,
                "Recipient format",
                "Recipient does not look like a "
                "Lightning Address, LNURL, npub, "
                "or nprofile. Continue anyway?",
                QMessageBox.Yes | QMessageBox.No,
            )

            if resp != QMessageBox.Yes:
                return

        if not amount_text:
            QMessageBox.warning(
                self,
                "Missing amount",
                "Please enter an amount (integer sats).",
            )
            return

        try:
            amount = int(amount_text)

            if amount < 0:
                raise ValueError(
                    "Amount negative"
                )

        except Exception:
            QMessageBox.warning(
                self,
                "Invalid amount",
                "Amount must be a non-negative "
                "integer (satoshis).",
            )
            return

        comment = (
            self.edit_comment.text().strip()
            or None
        )

        # Disable UI while generating.
        self.btn_generate.setEnabled(False)

        self.lbl_status.setText(
            "Generating invoice..."
        )

        self.edit_invoice.clear()

        self._thread = QThread(self)

        self._worker = InvoiceWorker(
            recipient,
            amount,
            comment,
        )

        self._worker.moveToThread(
            self._thread
        )

        self._thread.started.connect(
            self._worker.run
        )

        self._worker.finished.connect(
            self.on_worker_finished
        )

        self._worker.finished.connect(
            self._thread.quit
        )

        self._worker.finished.connect(
            self._worker.deleteLater
        )

        self._thread.finished.connect(
            self._thread.deleteLater
        )

        self._thread.start()

    # -------------------------------------------------------------------
    # Invoice result
    # -------------------------------------------------------------------

    def on_worker_finished(self, result: dict):
        self.btn_generate.setEnabled(True)

        if result.get("status") == "ok":
            bolt11 = result.get("bolt11")

            if not bolt11:
                self.lbl_status.setText(
                    "Error: get_bolt11 returned no invoice."
                )
                return

            self.edit_invoice.setText(
                bolt11
            )

            self.edit_invoice.selectAll()
            self.edit_invoice.setFocus()

            pixmap = generate_invoice_qr(
                bolt11
            )

            self.lbl_qr.setPixmap(
                pixmap
            )

            self.lbl_status.setText(
                "Invoice and QR generated successfully. "
                "Double-click to copy to clipboard."
            )

        else:
            msg = result.get(
                "msg",
                "Unknown error",
            )

            self.lbl_status.setText(
                f"Error: {msg}"
            )

            self.lbl_qr.clear()

            QMessageBox.critical(
                self,
                "Error",
                str(msg),
            )

    # -------------------------------------------------------------------
    # Copy invoice
    # -------------------------------------------------------------------

    def on_copy_invoice(self):
        text = self.edit_invoice.text()

        if not text:
            QMessageBox.information(
                self,
                "Nothing to copy",
                "There is no invoice to copy.",
            )
            return

        QApplication.clipboard().setText(
            text,
            mode=QClipboard.Clipboard,
        )

        self.lbl_status.setText(
            "Invoice copied to clipboard."
        )

    # -------------------------------------------------------------------
    # Shutdown
    # -------------------------------------------------------------------

    def shutdown(self):
        """Stop all worker threads before application exits."""

        threads = (
            self._thread,
            self._lnurl_thread,
        )

        self._thread = None
        self._worker = None

        self._lnurl_thread = None
        self._lnurl_worker = None

        for thread in threads:
            if thread is None:
                continue

            try:
                if thread.isRunning():
                    thread.requestInterruption()
                    thread.quit()
                    thread.wait()

            except RuntimeError:
                # Qt already deleted the underlying C++ object.
                pass


# ---------------------------------------------------------------------------
# Command line argument
# ---------------------------------------------------------------------------

def parse_recipient_argument() -> Optional[str]:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "address",
        nargs="?",
    )

    args = parser.parse_args()

    if not args.address:
        return None

    return normalize_recipient(
        args.address
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    recipient = parse_recipient_argument()

    app = QApplication(sys.argv)

    if get_bolt11 is None:
        QMessageBox.critical(
            None,
            "Import Error",
            "Could not import get_bolt11 from "
            "lnaddress2invoice.py.\n"
            "Make sure lnaddress2invoice.py is in the "
            "same directory and is importable.",
        )

    window = MainWindow()

    app.aboutToQuit.connect(
        window.shutdown
    )

    if recipient:
        window.edit_recipient.setText(
            recipient
        )

        # Resolve initial command-line recipient.
        window.on_lnaddress_finished()

    window.show()

    sys.exit(
        app.exec()
    )


if __name__ == "__main__":
    main()
