"""Application style sheet (SpecDash look with a yellow accent)."""

ACCENT = "#f5b800"

STYLE = """
* { font-family: "Helvetica Neue", "Segoe UI", Arial, sans-serif; font-size: 13px; color: #0b0b0b; }
QMainWindow, QWidget#root, QWidget#sidebar, QWidget#content { background: #f3f4f6; }
QScrollArea { border: none; background: transparent; }
QWidget#topbar { background: #ffffff; border-bottom: 1px solid #e4e7eb; }
QLabel#brand { font-size: 17px; font-weight: 700; }
QLabel#version { color: #8a8f98; font-size: 12px; }
QFrame#card { background: #ffffff; border: 1px solid #e4e7eb; border-radius: 12px; }
QFrame#card QLabel { background: transparent; }
QFrame#group { background: #f3f4f6; border: none; border-radius: 10px; }
QFrame#group QLabel { background: transparent; }
QLabel[role="caption"] { font-size: 10px; font-weight: 700; color: #8a8f98; padding-right: 4px; }
QLabel#h2 { font-size: 14px; font-weight: 700; }
QLabel[role="field"] { font-size: 12px; font-weight: 600; color: #50555e; }
QLabel[role="muted"] { font-size: 12px; color: #50555e; }
QLabel[role="badge"] { background: #fff3c4; color: #8a6100; border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: 700; }
QLabel[role="alert"] { background: #fff6e0; border: 1px solid #f2d48a; border-radius: 8px; padding: 8px 12px; }
QLabel[role="alert"][error="true"] { background: #fdeceb; border-color: #f0b4b3; }

QPushButton {
  padding: 7px 14px; border: 1px solid #d3d7dd; border-radius: 8px; background: #ffffff; font-weight: 500;
}
QPushButton:hover { background: #f3f4f6; border-color: #8a8f98; }
QPushButton:pressed { background: #e4e7eb; }
QPushButton:disabled { color: #a0a4ab; background: #ffffff; border-color: #e4e7eb; }
QPushButton[primary="true"] { background: #f5b800; border-color: #f5b800; color: #1a1400; font-weight: 600; }
QPushButton[primary="true"]:hover { background: #e0a800; border-color: #e0a800; }
QPushButton[primary="true"]:disabled { background: #fbe39a; border-color: #fbe39a; color: #8a7a3a; }
QPushButton[danger="true"] { color: #b42828; border-color: #f0b4b3; }
QPushButton[danger="true"]:hover { background: #fdeceb; border-color: #b42828; }
QPushButton[danger="true"]:disabled { color: #a0a4ab; border-color: #e4e7eb; background: #ffffff; }
QPushButton[pill="true"] { padding: 4px 10px; font-size: 12px; font-weight: 400; color: #50555e; }
QPushButton[pill="true"]:hover { color: #0b0b0b; }
QPushButton[pill="true"]:checked { background: #f5b800; border-color: #f5b800; color: #1a1400; font-weight: 600; }
QPushButton[pill="true"]:disabled { color: #a0a4ab; background: #f3f4f6; }

QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {
  border: 1px solid #d3d7dd; border-radius: 8px; padding: 6px 10px; background: #ffffff;
  selection-background-color: #fff3c4; selection-color: #0b0b0b;
}
QLineEdit:hover, QDoubleSpinBox:hover, QSpinBox:hover, QComboBox:hover { border-color: #8a8f98; }
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus, QComboBox:on { border-color: #f5b800; }
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button { width: 0; border: none; }
QComboBox:disabled, QLineEdit:disabled { background: #f3f4f6; color: #a0a4ab; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
  border: 1px solid #e4e7eb; background: #ffffff; selection-background-color: #fff3c4;
  selection-color: #0b0b0b; outline: 0; padding: 4px;
}

QProgressBar { border: none; border-radius: 4px; background: #e4e7eb; min-height: 8px; max-height: 8px; color: transparent; }
QProgressBar::chunk { background: #f5b800; border-radius: 4px; }

QGraphicsView { border: 1px solid #e4e7eb; border-radius: 8px; background: #ffffff; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #d3d7dd; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolTip { border: 1px solid #e4e7eb; background: #ffffff; color: #0b0b0b; padding: 4px 8px; }
"""
