"""
Style module for Novecento EMG Application.
Modern dark theme with Imperial Blue accent and Lexend font.
"""

from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtWidgets import QApplication
from pathlib import Path
import os


# Color palette
COLORS = {
    'bg_primary': '#0e1318',
    'bg_secondary': '#161b20',
    'bg_tertiary': '#1e242b',
    'accent': '#003E74',
    'accent_hover': '#004a8f',
    'accent_light': '#005aa6',
    'text_primary': '#e8eaed',
    'text_secondary': '#9da3ab',
    'text_muted': '#5a6169',
    'border': '#2d3139',
    'success': '#48BB78',
    'warning': '#F6AD55',
    'error': '#fc8181',
    'info': '#4a9eff',
    'pink': '#ff6b9d',
    'purple': '#a78bfa',
}


def load_fonts():
    """Load Lexend fonts into Qt application."""
    font_dir = Path(__file__).parent / "fonts"
    
    font_files = [
        "Lexend-Regular.ttf",
        "Lexend-Light.ttf",
        "Lexend-Medium.ttf",
        "Lexend-SemiBold.ttf",
        "Lexend-Bold.ttf",
        "Lexend-ExtraBold.ttf",
    ]
    
    loaded = 0
    for font_file in font_files:
        font_path = font_dir / font_file
        if font_path.exists():
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            if font_id >= 0:
                loaded += 1
    
    return loaded > 0


def get_stylesheet():
    """
    Modern dark theme with Imperial Blue and Lexend font.
    Clean, professional styling optimized for data visualization applications.
    """
    font_family = "Lexend"
    
    return f"""
        /* ========== BASE WIDGET ========== */
        QWidget {{
            background-color: {COLORS['bg_primary']}; 
            color: {COLORS['text_primary']};
            font-family: '{font_family}', 'Segoe UI', sans-serif;
            font-size: 11pt;
            font-weight: 400;
        }}

        /* ========== MAIN WINDOW ========== */
        QMainWindow {{
            background-color: {COLORS['bg_primary']};
        }}

        /* ========== LABELS ========== */
        QLabel {{
            font-family: '{font_family}', 'Segoe UI', sans-serif;
            color: {COLORS['text_primary']};
            background-color: transparent;
            padding: 2px;
        }}
        
        QLabel[heading="true"] {{
            font-size: 14pt;
            font-weight: 600;
            color: #ffffff;
        }}

        /* ========== TAB WIDGET ========== */
        QTabWidget::pane {{
            border: 1px solid {COLORS['border']};
            border-radius: 8px;
            background-color: {COLORS['bg_secondary']};
            margin-top: -1px;
        }}

        QTabBar {{
            font-family: '{font_family}', 'Segoe UI', sans-serif;
        }}

        QTabBar::tab {{
            font-family: '{font_family}', 'Segoe UI', sans-serif;
            background: transparent;
            color: {COLORS['text_secondary']};
            border: none;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            padding: 12px 24px;
            min-width: 100px;
            margin-right: 4px;
            font-weight: 500;
            font-size: 11pt;
        }}

        QTabBar::tab:hover {{
            background: {COLORS['bg_tertiary']};
            color: {COLORS['text_primary']};
        }}

        QTabBar::tab:selected {{
            background: {COLORS['bg_secondary']};
            color: #ffffff;
            font-weight: 600;
            border-bottom: 3px solid {COLORS['accent']};
        }}

        /* ========== BUTTONS ========== */
        QPushButton {{
            font-family: '{font_family}', 'Segoe UI', sans-serif;
            background-color: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {COLORS['accent_hover']}, 
                stop:1 {COLORS['accent']}
            );
            color: white;
            border: none;
            border-radius: 6px;
            padding: 10px 20px;
            font-weight: 600;
            font-size: 11pt;
        }}
        
        QPushButton:hover {{
            background-color: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {COLORS['accent_light']}, 
                stop:1 {COLORS['accent_hover']}
            );
        }}
        
        QPushButton:pressed {{
            background-color: #002952;
            padding: 11px 20px 9px 20px;
        }}
        
        QPushButton:disabled {{
            background-color: {COLORS['bg_tertiary']};
            color: {COLORS['text_muted']};
        }}

        /* Special button styles */
        QPushButton[class="success"] {{
            background-color: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 #38a169, 
                stop:1 #2f855a
            );
        }}
        
        QPushButton[class="success"]:hover {{
            background-color: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 #48bb78, 
                stop:1 #38a169
            );
        }}

        QPushButton[class="danger"] {{
            background-color: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 #e53e3e, 
                stop:1 #c53030
            );
        }}
        
        QPushButton[class="danger"]:hover {{
            background-color: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 #fc8181, 
                stop:1 #e53e3e
            );
        }}

        QPushButton[class="secondary"] {{
            background-color: {COLORS['bg_tertiary']};
            border: 2px solid {COLORS['border']};
        }}
        
        QPushButton[class="secondary"]:hover {{
            background-color: {COLORS['border']};
            border: 2px solid {COLORS['accent']};
        }}

        /* ========== INPUT FIELDS ========== */
        QLineEdit {{
            font-family: '{font_family}', 'Segoe UI', sans-serif;
            background-color: {COLORS['bg_primary']};
            color: {COLORS['text_primary']};
            font-size: 11pt;
            border: 2px solid {COLORS['border']};
            border-radius: 6px;
            padding: 8px 12px;
            selection-background-color: {COLORS['accent']};
        }}

        QLineEdit:focus {{
            border: 2px solid {COLORS['accent']};
            background-color: {COLORS['bg_secondary']};
        }}
        
        QLineEdit:read-only {{
            background-color: {COLORS['bg_tertiary']};
            color: {COLORS['text_secondary']};
        }}

        /* ========== COMBO BOX ========== */
        QComboBox {{
            font-family: '{font_family}', 'Segoe UI', sans-serif;
            background-color: {COLORS['bg_primary']};
            color: {COLORS['text_primary']};
            font-size: 11pt;
            border: 2px solid {COLORS['border']};
            border-radius: 6px;
            padding: 8px 12px;
            selection-background-color: {COLORS['accent']};
        }}

        QComboBox:focus {{
            border: 2px solid {COLORS['accent']};
            background-color: {COLORS['bg_secondary']};
        }}

        QComboBox::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 30px;
            border-left: 2px solid {COLORS['border']};
            border-top-right-radius: 6px;
            border-bottom-right-radius: 6px;
            background: {COLORS['bg_tertiary']};
        }}

        QComboBox::down-arrow {{
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 6px solid {COLORS['text_secondary']};
            margin-right: 8px;
        }}
        
        QComboBox::down-arrow:hover {{
            border-top: 6px solid {COLORS['text_primary']};
        }}

        QComboBox QAbstractItemView {{
            font-family: '{font_family}', 'Segoe UI', sans-serif;
            border: 2px solid {COLORS['accent']};
            background-color: {COLORS['bg_secondary']};
            selection-background-color: {COLORS['accent']};
            selection-color: #ffffff;
            border-radius: 6px;
            padding: 4px;
        }}
        
        QComboBox:disabled {{
            background-color: {COLORS['bg_tertiary']};
            color: {COLORS['text_muted']};
            border-color: {COLORS['bg_tertiary']};
        }}

        /* ========== SPIN BOX ========== */
        QSpinBox, QDoubleSpinBox {{
            font-family: '{font_family}', 'Segoe UI', sans-serif;
            background-color: {COLORS['bg_primary']};
            color: {COLORS['text_primary']};
            font-size: 11pt;
            border: 2px solid {COLORS['border']};
            border-radius: 6px;
            padding: 8px 12px;
            selection-background-color: {COLORS['accent']};
        }}

        QSpinBox:focus, QDoubleSpinBox:focus {{
            border: 2px solid {COLORS['accent']};
            background-color: {COLORS['bg_secondary']};
        }}

        QSpinBox::up-button, QDoubleSpinBox::up-button,
        QSpinBox::down-button, QDoubleSpinBox::down-button {{
            background-color: {COLORS['bg_tertiary']};
            border: none;
            width: 20px;
        }}

        QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
        QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
            background-color: {COLORS['accent']};
        }}

        /* ========== CHECKBOX ========== */
        QCheckBox {{
            font-family: '{font_family}', 'Segoe UI', sans-serif;
            spacing: 10px;
            font-size: 11pt;
        }}

        QCheckBox::indicator {{
            width: 20px;
            height: 20px;
            border: 2px solid {COLORS['border']};
            border-radius: 4px;
            background-color: {COLORS['bg_primary']};
        }}

        QCheckBox::indicator:checked {{
            background-color: {COLORS['accent']};
            border: 2px solid {COLORS['accent']};
        }}

        QCheckBox::indicator:hover {{
            border: 2px solid {COLORS['accent_hover']};
        }}

        /* ========== SCROLL BAR ========== */
        QScrollBar:vertical {{
            border: none;
            background: {COLORS['bg_primary']};
            width: 10px;
            margin: 2px;
            border-radius: 5px;
        }}

        QScrollBar::handle:vertical {{
            background: {COLORS['border']};
            min-height: 30px;
            border-radius: 5px;
        }}

        QScrollBar::handle:vertical:hover {{
            background: {COLORS['accent']};
        }}

        QScrollBar:horizontal {{
            border: none;
            background: {COLORS['bg_primary']};
            height: 10px;
            margin: 2px;
            border-radius: 5px;
        }}

        QScrollBar::handle:horizontal {{
            background: {COLORS['border']};
            min-width: 30px;
            border-radius: 5px;
        }}

        QScrollBar::handle:horizontal:hover {{
            background: {COLORS['accent']};
        }}

        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            height: 0px;
            width: 0px;
        }}
        
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
            background: none;
        }}

        /* ========== GROUP BOX ========== */
        QGroupBox {{
            font-family: '{font_family}', 'Segoe UI', sans-serif;
            border: 2px solid {COLORS['border']};
            border-radius: 8px;
            margin-top: 24px;
            padding-top: 20px;
            font-weight: 600;
            font-size: 11pt;
            background-color: {COLORS['bg_secondary']};
        }}

        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 16px;
            padding: 4px 12px;
            color: {COLORS['accent']};
            background-color: {COLORS['bg_primary']};
            border-radius: 4px;
        }}

        /* ========== PROGRESS BAR ========== */
        QProgressBar {{
            font-family: '{font_family}', 'Segoe UI', sans-serif;
            border: none;
            border-radius: 6px;
            background-color: {COLORS['bg_tertiary']};
            text-align: center;
            color: white;
            font-size: 10pt;
            font-weight: 500;
        }}

        QProgressBar::chunk {{
            background-color: qlineargradient(
                x1:0, y1:0, x2:1, y2:0,
                stop:0 {COLORS['accent']},
                stop:1 {COLORS['accent_light']}
            );
            border-radius: 6px;
        }}

        /* ========== TABLE WIDGET ========== */
        QTableView, QTableWidget {{
            font-family: '{font_family}', 'Segoe UI', sans-serif;
            background-color: {COLORS['bg_primary']};
            alternate-background-color: {COLORS['bg_secondary']};
            border: 1px solid {COLORS['border']};
            border-radius: 6px;
            gridline-color: {COLORS['border']};
            selection-background-color: {COLORS['accent']};
            font-size: 10pt;
        }}

        QTableView::item, QTableWidget::item {{
            padding: 8px;
        }}

        QHeaderView::section {{
            font-family: '{font_family}', 'Segoe UI', sans-serif;
            background-color: {COLORS['bg_tertiary']};
            color: {COLORS['text_primary']};
            padding: 10px;
            border: none;
            border-bottom: 2px solid {COLORS['accent']};
            font-weight: 600;
            font-size: 10pt;
        }}

        /* ========== LIST WIDGET ========== */
        QListView, QListWidget {{
            font-family: '{font_family}', 'Segoe UI', sans-serif;
            background-color: {COLORS['bg_primary']};
            border: 1px solid {COLORS['border']};
            border-radius: 6px;
            selection-background-color: {COLORS['accent']};
            font-size: 11pt;
        }}

        QListView::item, QListWidget::item {{
            padding: 8px;
            border-radius: 4px;
        }}

        QListView::item:hover, QListWidget::item:hover {{
            background-color: {COLORS['bg_tertiary']};
        }}

        QListView::item:selected, QListWidget::item:selected {{
            background-color: {COLORS['accent']};
        }}

        /* ========== MENU ========== */
        QMenuBar {{
            font-family: '{font_family}', 'Segoe UI', sans-serif;
            background-color: {COLORS['bg_primary']};
            color: {COLORS['text_primary']};
            border-bottom: 1px solid {COLORS['border']};
            font-size: 11pt;
        }}

        QMenuBar::item {{
            padding: 8px 16px;
            background: transparent;
        }}

        QMenuBar::item:selected {{
            background-color: {COLORS['bg_tertiary']};
        }}

        QMenu {{
            font-family: '{font_family}', 'Segoe UI', sans-serif;
            background-color: {COLORS['bg_secondary']};
            border: 1px solid {COLORS['border']};
            border-radius: 6px;
            padding: 4px;
            font-size: 11pt;
        }}

        QMenu::item {{
            padding: 8px 24px;
            border-radius: 4px;
        }}

        QMenu::item:selected {{
            background-color: {COLORS['accent']};
        }}

        QMenu::separator {{
            height: 1px;
            background: {COLORS['border']};
            margin: 4px 8px;
        }}

        /* ========== TEXT EDIT ========== */
        QTextEdit, QPlainTextEdit {{
            font-family: 'Consolas', monospace;
            background-color: {COLORS['bg_primary']};
            color: {COLORS['text_primary']};
            border: 2px solid {COLORS['border']};
            border-radius: 6px;
            padding: 8px;
            font-size: 10pt;
            selection-background-color: {COLORS['accent']};
        }}

        QTextEdit:focus, QPlainTextEdit:focus {{
            border: 2px solid {COLORS['accent']};
        }}

        /* ========== STATUS BAR ========== */
        QStatusBar {{
            font-family: '{font_family}', 'Segoe UI', sans-serif;
            background-color: {COLORS['bg_secondary']};
            color: {COLORS['text_secondary']};
            border-top: 1px solid {COLORS['border']};
            font-size: 10pt;
        }}

        /* ========== SPLITTER ========== */
        QSplitter::handle {{
            background-color: {COLORS['border']};
            width: 2px;
            height: 2px;
        }}

        QSplitter::handle:hover {{
            background-color: {COLORS['accent']};
        }}

        /* ========== TOOLTIP ========== */
        QToolTip {{
            font-family: '{font_family}', 'Segoe UI', sans-serif;
            background-color: {COLORS['bg_tertiary']};
            color: #ffffff;
            border: 1px solid {COLORS['accent']};
            border-radius: 6px;
            padding: 8px 12px;
            font-size: 10pt;
        }}

        /* ========== MESSAGE BOX ========== */
        QMessageBox {{
            font-family: '{font_family}', 'Segoe UI', sans-serif;
            background-color: {COLORS['bg_primary']};
        }}

        QMessageBox QLabel {{
            font-family: '{font_family}', 'Segoe UI', sans-serif;
            color: {COLORS['text_primary']};
            font-size: 11pt;
        }}
    """


def apply_style(widget):
    """Apply the Imperial Blue dark theme to a widget."""
    load_fonts()
    widget.setStyleSheet(get_stylesheet())