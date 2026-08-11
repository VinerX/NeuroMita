from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QAbstractSpinBox, QHBoxLayout, QSpinBox, QToolButton, QWidget


class NumberStepper(QWidget):
    valueChanged = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NumberStepper")
        self.setMinimumWidth(132)
        self.setFixedHeight(40)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.decrease_button = QToolButton(self)
        self.decrease_button.setObjectName("NumberStepperDecrease")
        self.decrease_button.setText("−")
        self.decrease_button.setAutoRepeat(True)
        self.decrease_button.setToolTip("Decrease")

        self.spin_box = QSpinBox(self)
        self.spin_box.setObjectName("NumberStepperValue")
        self.spin_box.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.spin_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spin_box.setKeyboardTracking(False)

        self.increase_button = QToolButton(self)
        self.increase_button.setObjectName("NumberStepperIncrease")
        self.increase_button.setText("+")
        self.increase_button.setAutoRepeat(True)
        self.increase_button.setToolTip("Increase")

        layout.addWidget(self.decrease_button)
        layout.addWidget(self.spin_box, 1)
        layout.addWidget(self.increase_button)

        self.decrease_button.clicked.connect(self.spin_box.stepDown)
        self.increase_button.clicked.connect(self.spin_box.stepUp)
        self.spin_box.valueChanged.connect(self.valueChanged)

    def setRange(self, minimum: int, maximum: int) -> None:
        self.spin_box.setRange(minimum, maximum)

    def setSingleStep(self, step: int) -> None:
        self.spin_box.setSingleStep(step)

    def setValue(self, value: int) -> None:
        self.spin_box.setValue(value)

    def value(self) -> int:
        return self.spin_box.value()

    def setSuffix(self, suffix: str) -> None:
        self.spin_box.setSuffix(suffix)

    def setSpecialValueText(self, text: str) -> None:
        self.spin_box.setSpecialValueText(text)

    def setToolTip(self, text: str) -> None:
        super().setToolTip(text)
        self.spin_box.setToolTip(text)
