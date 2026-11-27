"""Dark pro-audio studio QSS stylesheet for TriTrack Studio."""

STUDIO_QSS = """
QMainWindow, QWidget {
    background-color: #0e1117;
    color: #e6edf3;
    font-family: "Segoe UI", "Inter", system-ui, sans-serif;
    font-size: 13px;
}

QFrame#TopBar {
    background-color: #161b22;
    border: 1px solid #262c36;
    border-radius: 12px;
}

QFrame#ChannelCard {
    background-color: #161b22;
    border: 1px solid #262c36;
    border-radius: 12px;
}

QFrame#ChannelCardCombined {
    background-color: #151c26;
    border: 1px solid #2d4363;
    border-radius: 12px;
}

QFrame#SettingsCard {
    background-color: #161b22;
    border: 1px solid #262c36;
    border-radius: 12px;
}

QLabel#AppTitle {
    font-size: 19px;
    font-weight: 700;
    color: #f0f6fc;
    background: transparent;
}

QLabel#BackendBadge {
    background-color: #1f2937;
    color: #79c0ff;
    border: 1px solid #30465e;
    border-radius: 6px;
    padding: 3px 9px;
    font-size: 11px;
    font-weight: 600;
}

QLabel#TimerDisplay {
    font-family: "Cascadia Mono", "Consolas", "JetBrains Mono", monospace;
    font-size: 26px;
    font-weight: 700;
    color: #f0f6fc;
    background-color: #0b0e14;
    border: 1px solid #262c36;
    border-radius: 8px;
    padding: 6px 14px;
}

QLabel#CardHeader {
    font-size: 14px;
    font-weight: 700;
    color: #f0f6fc;
    background: transparent;
}

QLabel#CardTag {
    font-size: 11px;
    font-weight: 700;
    color: #8b949e;
    background: transparent;
    letter-spacing: 0.6px;
}

QLabel#MutedLabel {
    color: #8b949e;
    font-size: 12px;
    background: transparent;
}

QLabel#FilePreview {
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
    color: #7ee787;
    background-color: #0d131a;
    border: 1px solid #212c38;
    border-radius: 6px;
    padding: 4px 8px;
}

QLabel#StatusIdle {
    background-color: #21262d;
    color: #8b949e;
    border-radius: 6px;
    padding: 4px 10px;
    font-weight: 700;
    font-size: 11px;
}

QLabel#StatusMonitoring {
    background-color: #132a1e;
    color: #3fb950;
    border: 1px solid #238636;
    border-radius: 6px;
    padding: 4px 10px;
    font-weight: 700;
    font-size: 11px;
}

QLabel#StatusRecording {
    background-color: #3d1217;
    color: #ff7b72;
    border: 1px solid #da3633;
    border-radius: 6px;
    padding: 4px 10px;
    font-weight: 700;
    font-size: 11px;
}

QLabel#StatusPaused {
    background-color: #33240c;
    color: #f2cc60;
    border: 1px solid #9e6a03;
    border-radius: 6px;
    padding: 4px 10px;
    font-weight: 700;
    font-size: 11px;
}

QPushButton {
    background-color: #21262d;
    color: #e6edf3;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 7px 14px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #30363d;
    border-color: #484f58;
}

QPushButton:disabled {
    background-color: #161b22;
    color: #484f58;
    border-color: #21262d;
}

QPushButton#RecordButton {
    background-color: #da3633;
    color: #ffffff;
    border: 1px solid #f85149;
    padding: 8px 18px;
    font-size: 13px;
}

QPushButton#RecordButton:hover {
    background-color: #e5534b;
}

QPushButton#RecordButton:disabled {
    background-color: #421a1a;
    color: #8b5555;
    border-color: #542222;
}

QPushButton#PauseButton {
    background-color: #9e6a03;
    color: #ffffff;
    border: 1px solid #d29922;
    padding: 8px 14px;
}

QPushButton#PauseButton:hover {
    background-color: #b57b05;
}

QPushButton#StopButton {
    background-color: #238636;
    color: #ffffff;
    border: 1px solid #2ea043;
    padding: 8px 16px;
}

QPushButton#StopButton:hover {
    background-color: #2ea043;
}

QPushButton#MuteButton {
    background-color: #21262d;
    border: 1px solid #30363d;
    padding: 5px 10px;
    font-size: 12px;
}

QPushButton#MuteButton:checked {
    background-color: #5a1e22;
    color: #ff7b72;
    border: 1px solid #da3633;
}

QComboBox, QLineEdit {
    background-color: #0d1117;
    color: #e6edf3;
    border: 1px solid #30363d;
    border-radius: 7px;
    padding: 6px 10px;
}

QComboBox:hover, QLineEdit:hover {
    border-color: #58a6ff;
}

QComboBox::drop-down {
    border: none;
    width: 22px;
}

QComboBox QAbstractItemView {
    background-color: #161b22;
    color: #e6edf3;
    border: 1px solid #30363d;
    selection-background-color: #1f6feb;
}

QSlider::groove:horizontal {
    height: 6px;
    background: #0d1117;
    border: 1px solid #262c36;
    border-radius: 3px;
}

QSlider::sub-page:horizontal {
    background: #2f81f7;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #f0f6fc;
    border: 2px solid #2f81f7;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 8px;
}

QCheckBox {
    spacing: 8px;
    background: transparent;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #30363d;
    background: #0d1117;
}

QCheckBox::indicator:checked {
    background: #238636;
    border-color: #3fb950;
}

QTableWidget {
    background-color: #0d1117;
    border: 1px solid #262c36;
    border-radius: 8px;
    gridline-color: #21262d;
    selection-background-color: #1f3a5f;
}

QHeaderView::section {
    background-color: #161b22;
    color: #8b949e;
    padding: 6px 8px;
    border: none;
    border-bottom: 1px solid #262c36;
    font-weight: 600;
    font-size: 11px;
}
"""
