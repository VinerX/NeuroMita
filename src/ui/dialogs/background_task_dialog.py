from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from ui.widgets.launcher_shell_theme import PALETTE
from utils import getTranslationVariant as _


_BACKGROUND_TASK_STYLE = f"""
QDialog#BackgroundTaskDialog {{
    background-color: {PALETTE.root_bg};
    color: {PALETTE.text};
}}
QFrame#BackgroundTaskCard {{
    background-color: {PALETTE.card_bg};
    border: 1px solid {PALETTE.border};
    border-radius: 20px;
}}
QLabel#BackgroundTaskEyebrow {{
    color: {PALETTE.accent_hover};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.12em;
}}
QLabel#BackgroundTaskTitle {{
    color: {PALETTE.text};
    font-size: 16px;
    font-weight: 700;
}}
QLabel#BackgroundTaskStatus {{
    color: {PALETTE.text};
    font-size: 13px;
}}
QLabel#BackgroundTaskDetail {{
    color: {PALETTE.muted};
    font-size: 12px;
}}
QLabel#BackgroundTaskHint {{
    color: {PALETTE.muted};
    font-size: 11px;
}}
QProgressBar#BackgroundTaskBar {{
    min-height: 16px;
    border: 1px solid {PALETTE.border};
    border-radius: 8px;
    background-color: {PALETTE.card_alt_bg};
    color: {PALETTE.text};
    text-align: center;
}}
QProgressBar#BackgroundTaskBar::chunk {{
    border-radius: 7px;
    background-color: {PALETTE.accent};
}}
QPushButton#BackgroundTaskGhostButton {{
    background-color: rgba(255, 255, 255, 0.04);
    color: {PALETTE.text};
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 12px;
    padding: 9px 16px;
    font-size: 13px;
    font-weight: 600;
    min-width: 120px;
}}
QPushButton#BackgroundTaskGhostButton:hover {{
    background-color: {PALETTE.accent_soft};
    border: 1px solid {PALETTE.border};
}}
QPushButton#BackgroundTaskDangerButton {{
    background-color: rgba(255, 255, 255, 0.03);
    color: {PALETTE.danger};
    border: 1px solid {PALETTE.danger};
    border-radius: 12px;
    padding: 9px 16px;
    font-size: 13px;
    font-weight: 600;
    min-width: 120px;
}}
QPushButton#BackgroundTaskDangerButton:hover {{
    background-color: {PALETTE.danger};
    color: {PALETTE.text};
}}
"""


class BackgroundTaskDialog(QDialog):
    """Немодальное окно прогресса фоновой задачи.

    В отличие от QProgressDialog здесь две кнопки: «Скрыть» убирает окно, а
    задача продолжает выполняться в фоне; «Остановить» реально прерывает её.
    Закрытие по [X] или Esc тоже только скрывает окно — случайно оборвать
    длинную переиндексацию нельзя. Для программного закрытия по завершении
    задачи используйте finish().
    """

    stopRequested = pyqtSignal()

    def __init__(
        self,
        parent=None,
        *,
        title: str = "",
        eyebrow: str = "",
        hint: str = "",
    ) -> None:
        super().__init__(parent)
        self._allow_close = False
        self._grow_pending = False

        self.setObjectName("BackgroundTaskDialog")
        self.setStyleSheet(_BACKGROUND_TASK_STYLE)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowTitle(title or _("Фоновая задача", "Background task"))
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        # Статус приходит уже после show() и бывает длинным (перенос на 2-3
        # строки). Без этого окно оставалось прежней высоты, карточка
        # ужималась, и нижний ряд кнопок обрезался краем окна.
        root.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        card = QFrame()
        card.setObjectName("BackgroundTaskCard")
        # Ширину задаём карточке, а не окну: SetMinimumSize у root-лейаута
        # перетирает minimumSize самого диалога.
        card.setMinimumWidth(480)
        # Без этого высота переносимых строк внутри карточки не доходит до
        # окна: QWidget по умолчанию не пробрасывает heightForWidth наружу.
        card_policy = card.sizePolicy()
        card_policy.setHeightForWidth(True)
        card.setSizePolicy(card_policy)
        root.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)

        if eyebrow:
            eyebrow_label = QLabel(eyebrow)
            eyebrow_label.setObjectName("BackgroundTaskEyebrow")
            layout.addWidget(eyebrow_label)

        if title:
            title_label = QLabel(title)
            title_label.setObjectName("BackgroundTaskTitle")
            title_label.setWordWrap(True)
            layout.addWidget(title_label)

        self._status_label = QLabel(_("Подготовка...", "Preparing..."))
        self._status_label.setObjectName("BackgroundTaskStatus")
        self._status_label.setWordWrap(True)
        self._status_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        # Место под две строки резервируем сразу, чтобы окно не «прыгало» на
        # каждой смене статуса.
        self._reserve_lines(self._status_label, 2)
        layout.addWidget(self._status_label)

        self._bar = QProgressBar()
        self._bar.setObjectName("BackgroundTaskBar")
        # Стартуем в режиме «занято» (бегущая полоса): пока не пришёл первый
        # тик прогресса (напр. идёт долгая загрузка модели), окно не выглядит
        # зависшим.
        self._bar.setRange(0, 0)
        self._bar.setTextVisible(False)
        layout.addWidget(self._bar)

        self._detail_label = QLabel("")
        self._detail_label.setObjectName("BackgroundTaskDetail")
        self._detail_label.setWordWrap(True)
        self._reserve_lines(self._detail_label, 1)
        layout.addWidget(self._detail_label)

        hint_text = hint or _(
            "Окно можно скрыть — задача продолжится в фоне.",
            "You can hide this window — the task keeps running in the background.",
        )
        hint_label = QLabel(hint_text)
        hint_label.setObjectName("BackgroundTaskHint")
        hint_label.setWordWrap(True)
        layout.addWidget(hint_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch()

        self._hide_button = QPushButton(_("Скрыть", "Hide"))
        self._hide_button.setObjectName("BackgroundTaskGhostButton")
        self._hide_button.clicked.connect(self.hide)
        buttons.addWidget(self._hide_button)

        self._stop_button = QPushButton(_("Остановить", "Stop"))
        self._stop_button.setObjectName("BackgroundTaskDangerButton")
        self._stop_button.clicked.connect(self._on_stop)
        buttons.addWidget(self._stop_button)

        layout.addLayout(buttons)

        self.adjustSize()

    @staticmethod
    def _reserve_lines(label: QLabel, lines: int) -> None:
        label.setMinimumHeight(label.fontMetrics().lineSpacing() * int(lines))

    def _schedule_grow_to_fit(self) -> None:
        # Пересчёт откладываем на следующий тик: Qt обновляет sizeHint только
        # после обработки LayoutRequest, поэтому сразу после setText размер
        # ещё старый.
        if self._grow_pending:
            return
        self._grow_pending = True
        QTimer.singleShot(0, self._grow_to_fit)

    def _grow_to_fit(self) -> None:
        """Подрасти под новый текст, если он не помещается (окно только
        растёт — иначе оно бы дёргалось на каждом тике прогресса)."""
        self._grow_pending = False
        layout = self.layout()
        if layout is None:
            return
        layout.activate()
        needed = self.sizeHint().height()
        if layout.hasHeightForWidth():
            needed = max(needed, layout.heightForWidth(self.width()))
        if needed > self.height():
            self.resize(self.width(), needed)

    # --- API прогресса (близко к QProgressDialog) --------------------------

    def set_status(self, text: str) -> None:
        self._status_label.setText(str(text or ""))
        self._schedule_grow_to_fit()

    def set_detail(self, text: str) -> None:
        self._detail_label.setText(str(text or ""))
        self._schedule_grow_to_fit()

    def set_range(self, minimum: int, maximum: int) -> None:
        top = int(maximum)
        self._bar.setRange(int(minimum), top)
        # В determinate-режиме показываем проценты прямо в полосе: пустая
        # полоса без единой цифры выглядела как «ничего не происходит».
        self._bar.setTextVisible(top > 0)

    def set_value(self, value: int) -> None:
        self._bar.setValue(int(value))

    def show_busy(self) -> None:
        self._bar.setRange(0, 0)
        self._bar.setTextVisible(False)

    # --- управление жизненным циклом --------------------------------------

    def _on_stop(self) -> None:
        self._stop_button.setEnabled(False)
        self._stop_button.setText(_("Остановка...", "Stopping..."))
        self.stopRequested.emit()

    def finish(self) -> None:
        """Реально закрыть окно (по завершении/ошибке фоновой задачи)."""
        self._allow_close = True
        self.close()

    def closeEvent(self, event):  # noqa: N802 (Qt override)
        if not self._allow_close:
            event.ignore()
            self.hide()
            return
        super().closeEvent(event)

    def keyPressEvent(self, event):  # noqa: N802 (Qt override)
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)
