"""The form for a token-only player's first password, as on the app: the new password twice,
since there is no other to fall back on when it was mistyped."""

from aqt.qt import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, Qt

from . import password_prompt
from .language import tr


def password_dialog(parent, on_submit):
    """`on_submit(password, finish)` sends it and calls `finish(error)`; the form stays open with
    the error until the server takes the password. True once it did."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(tr("Set a password"))
    layout = QVBoxLayout(dialog)

    # The two fields, then where a problem is said.
    fields = []
    for hint in (tr("New password"), tr("New password again")):
        field = QLineEdit()
        field.setEchoMode(QLineEdit.EchoMode.Password)
        field.setPlaceholderText(hint)
        layout.addWidget(field)
        fields.append(field)
    status = QLabel()
    status.setTextFormat(Qt.TextFormat.PlainText)
    status.setWordWrap(True)
    layout.addWidget(status)

    row = QHBoxLayout()
    row.addStretch(1)
    cancel = QPushButton(tr("Cancel"))
    cancel.clicked.connect(dialog.reject)
    save = QPushButton(tr("Save"))
    save.setDefault(True)
    row.addWidget(cancel)
    row.addWidget(save)
    layout.addLayout(row)

    def finish(error):
        save.setEnabled(True)
        if error:
            status.setText(error)
            return
        dialog.accept()

    def go():
        password, repeat = fields[0].text(), fields[1].text()
        problem = password_prompt._problem(password, repeat)
        if problem is not None:
            status.setText(tr(problem))
            return
        save.setEnabled(False)
        status.setText(tr("Connecting…"))
        on_submit(password, finish)

    save.clicked.connect(go)
    return bool(dialog.exec())
