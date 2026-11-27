"""CLI and GUI entry point for TriTrack Studio."""

from __future__ import annotations

import argparse
import logging
import sys

from . import __app_name__, __version__
from .backends import create_backend
from .config import RecorderConfig
from .engine import RecordingEngine


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="tritrack",
        description=f"{__app_name__} v{__version__} — Windows 3-Output Hi-Fi Stereo Audio Recorder",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run with simulated stereo studio devices (useful for previewing UI without audio hardware).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{__app_name__} {__version__}",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = parse_args(argv)

    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)

    try:
        backend = create_backend(force_simulated=args.demo)
    except Exception as exc:
        QMessageBox.critical(
            None,
            f"{__app_name__} — Audio Backend Error",
            f"Could not initialize Windows WASAPI audio backend:\n\n{exc}",
        )
        return 1

    config = RecorderConfig.load()
    engine = RecordingEngine(backend=backend, config=config)

    from .ui.main_window import MainWindow

    window = MainWindow(engine)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
