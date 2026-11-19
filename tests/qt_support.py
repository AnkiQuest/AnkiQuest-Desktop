"""Setup the real-Qt checks (qt_*.py) share: the QApplication, Anki's main window and its background tasks."""

from concurrent.futures import Future
from types import SimpleNamespace

from aqt.qt import QApplication, QWidget

app = QApplication.instance() or QApplication([])


def complete(task):
    """Runs a queued (work, done) pair as Anki's task manager would: done gets what work returned or raised."""
    work, done = task
    future = Future()
    try:
        future.set_result(work())
    except Exception as error:
        future.set_exception(error)
    done(future)


def run_now(work, done, **_options):
    """A run_in_background that finishes the work at once."""
    complete((work, done))


def queue(tasks):
    """A run_in_background that keeps each (work, done) in `tasks` for finish()."""
    return lambda work, done, **_options: tasks.append((work, done))


def finish(tasks, index=0, error=None):
    """Answers queued task `index` with its work's result, or with `error`, then lets Qt handle the reply."""
    work, done = tasks.pop(index)
    future = Future()
    if error is None:
        future.set_result(work())
    else:
        future.set_exception(error)
    done(future)
    app.processEvents()


def main_window(run=None):
    """A real widget standing in for Anki's main window, with an empty profile and `run` as run_in_background."""
    window = QWidget()
    window.pm = SimpleNamespace(profile={})
    window.taskman = SimpleNamespace(run_in_background=run)
    return window


def stand_in(run):
    """Anki's main window where no widget is needed: an empty profile and `run` as run_in_background."""
    return SimpleNamespace(pm=SimpleNamespace(profile={}), taskman=SimpleNamespace(run_in_background=run))
