# -*- coding: utf-8 -*-
"""
QJobProgressDialog: progress and cancel for a :class:`PyQTango.models.Job`
(replaces Jive's ProgressFrame and ThreadDlg).
"""

from ..qt import QtWidgets, Qt, is_deleted
from .errors import QErrorDialog


class QJobProgressDialog(QtWidgets.QProgressDialog):
    """ Runs a Job, shows its progress, cancels it on request and, at the end,
    shows the non-fatal errors the job collected (or the fatal one).

    Example::

        def apply(job, devices):
            for i, d in enumerate(devices):
                if job.cancelled:
                    break
                job.set_progress(100 * i // len(devices), "Updating " + d)
                try:
                    ...
                except tango.DevFailed as e:
                    job.add_error(e, d)

        QJobProgressDialog.run(Job(apply, devices, title="Updating"), parent)
    """

    def __init__(self, job, parent=None, show_errors=True):
        QtWidgets.QProgressDialog.__init__(self, job.title or "Working...", "Cancel", 0, 100, parent)
        self.job = job
        self.show_errors = show_errors
        self.setWindowTitle(job.title or "Progress")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumDuration(300)
        self.setAutoClose(False)
        self.setAutoReset(False)
        self.canceled.connect(job.cancel)
        job.progress.connect(self._on_progress)
        job.failed.connect(self._on_failed)
        job.finished.connect(self._on_finished)
        self.fatal = None

    def _on_progress(self, percent, text):
        if is_deleted(self):            # its window was closed while the job ran
            return
        self.setValue(max(0, min(100, percent)))
        if text:
            self.setLabelText(text)

    def _on_failed(self, err):
        self.fatal = err

    def _on_finished(self):
        if is_deleted(self):
            return
        self.setValue(100)
        self.close()
        try:
            self._show_errors()
        finally:
            self.deleteLater()      # one dialog per job: do not pile them up under the parent

    def _show_errors(self):
        if not self.show_errors:
            return
        if self.fatal is not None:
            QErrorDialog(self.fatal, self.job.title or "Error", self.parentWidget()).exec()
        elif self.job.errors:
            msg = QtWidgets.QMessageBox(self.parentWidget())
            msg.setIcon(QtWidgets.QMessageBox.Icon.Warning)
            msg.setWindowTitle(self.job.title or "Errors")
            msg.setText("{0} error(s) occurred.".format(len(self.job.errors)))
            msg.setDetailedText("\n\n".join(e.text() for e in self.job.errors))
            msg.exec()

    @classmethod
    def run(cls, job, parent=None, show_errors=True):
        """ Start ``job`` with a progress dialog; returns the dialog """
        dlg = cls(job, parent, show_errors)
        job.start()
        return dlg
