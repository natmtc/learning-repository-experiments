#!/usr/bin/env python3
"""
MINIMAL TEST - Does the button work at all?

Run this to test if the button system works:
    python test_button.py
"""

from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QLabel
import sys

class TestWindow(QWidget):
    def __init__(self):
        super().__init__()
        
        layout = QVBoxLayout(self)
        
        self.label = QLabel("Button should be GREEN and clickable")
        layout.addWidget(self.label)
        
        # Create button EXACTLY like bartask
        self.test_btn = QPushButton("▶ Test Button")
        self.test_btn.setEnabled(True)
        self.test_btn.setMinimumHeight(45)
        self.test_btn.setStyleSheet(
            "QPushButton { background-color: #48BB78; color: white; "
            "font-weight: bold; font-size: 14px; }"
        )
        self.test_btn.clicked.connect(self.on_click)
        layout.addWidget(self.test_btn)
        
        self.result_label = QLabel("")
        layout.addWidget(self.result_label)
        
        self.setWindowTitle("Button Test")
        self.resize(400, 200)
        
    def on_click(self):
        self.result_label.setText("✅ BUTTON WORKS!")
        self.result_label.setStyleSheet("color: green; font-size: 20px;")
        print("✅ Button clicked successfully!")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TestWindow()
    window.show()
    sys.exit(app.exec())
