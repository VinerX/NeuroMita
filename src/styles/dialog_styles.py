# dialog_styles.py

def get_dialog_stylesheet():
    return """
        QDialog#ActionDialog {
            background-color: #1e1e1e;
            color: #dcdcdc;
            border: 1px solid #4a4a4a;
        }
        
        QDialog#ActionDialog QLabel {
            background-color: transparent;
            color: #dcdcdc;
        }

        QDialog#ActionDialog QLabel#TitleLabel {
            font-size: 11pt;
            font-weight: bold;
        }

        QDialog#ActionDialog QLabel#WarningLabel {
            font-weight: bold;
            color: orange;
        }

        QDialog#ActionDialog QTextEdit#LogArea {
            background-color: #101010;
            color: #cccccc;
            font-family: "Consolas", "Courier New", monospace;
            font-size: 9pt;
            border: 1px solid #4a4a4a;
        }

        QDialog#ActionDialog QProgressBar {
            border: 1px solid #555555;
            border-radius: 2px;
            text-align: center;
            background-color: #555555;
            color: #dcdcdc;
            height: 12px;
        }

        QDialog#ActionDialog QProgressBar::chunk {
            background-color: #db6596;
            border-radius: 2px;
        }

        QDialog#ActionDialog QPushButton {
            background-color: #333333;
            color: #ffffff;
            border: 1px solid #555555;
            padding: 5px 14px;
            border-radius: 3px;
        }
        QDialog#ActionDialog QPushButton:hover {
            background-color: #444444;
            border-color: #666666;
        }
        QDialog#ActionDialog QPushButton:pressed {
            background-color: #2a2a2a;
        }
        QDialog#ActionDialog QPushButton:disabled {
            background-color: #252525;
            color: #777777;
            border-color: #444444;
        }
        
        QDialog#ActionDialog QPushButton#RetryButton {
            background-color: #db6596;
            font-weight: bold;
        }
        QDialog#ActionDialog QPushButton#RetryButton:hover {
            background-color: #e26e9e;
        }

        QDialog#ActionDialog QPushButton#ContinueButton {
            background-color: #db6596;
            font-weight: bold;
        }
        QDialog#ActionDialog QPushButton#ContinueButton:hover {
            background-color: #e26e9e;
        }
    """