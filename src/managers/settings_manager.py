
try:
    import qtawesome as qta
except Exception:
    qta = None
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QApplication, QStyle
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

from main_logger import logger

import json, os, sys, threading, queue, time, atexit

class SettingsManager:
    instance = None
    SAVE_DEBOUNCE_SEC = 0.5          # сколько «выжидать», собирая изменения
    _SENTINEL = object()             # сигнал завершения потока
    _fallback_settings: dict = {}
    _fallback_path: str | None = None
    _fallback_mtime: float | None = None

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.settings: dict = {}
        self._save_queue: "queue.Queue[object]" = queue.Queue()
        self._writer_thread = threading.Thread(
            target=self._save_worker, name="SettingsSaver", daemon=True)
        self._writer_thread.start()
        atexit.register(self._stop_writer)      # финальное сохранение

        self.load_settings()
        SettingsManager.instance = self         # singleton

    # ---------- публичное API ----------

    @staticmethod
    def get(key, default=None):
        inst = SettingsManager.instance
        if inst:
            return inst.settings.get(key, default)
        fallback = SettingsManager._load_fallback_settings()
        return fallback.get(key, default)

    @staticmethod
    def set(key, value):
        inst = SettingsManager.instance
        if not inst:
            logger.error("SettingsManager.set() called before init")
            return
        inst.settings[key] = value
        inst._schedule_save()

    @staticmethod
    def _fallback_config_path() -> str:
        base_dir = os.environ.get("NEUROMITA_BASE_DIR")
        if not base_dir:
            base_dir = os.path.dirname(os.path.abspath(sys.executable))
        return os.path.join(base_dir, "Settings", "settings.json")

    @staticmethod
    def _load_fallback_settings() -> dict:
        path = SettingsManager._fallback_config_path()
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            SettingsManager._fallback_settings = {}
            SettingsManager._fallback_path = path
            SettingsManager._fallback_mtime = None
            return SettingsManager._fallback_settings

        if (
            SettingsManager._fallback_path == path
            and SettingsManager._fallback_mtime == mtime
        ):
            return SettingsManager._fallback_settings

        try:
            with open(path, "r", encoding="utf-8") as f:
                SettingsManager._fallback_settings = json.load(f)
        except (OSError, json.JSONDecodeError):
            SettingsManager._fallback_settings = {}
        SettingsManager._fallback_path = path
        SettingsManager._fallback_mtime = mtime
        return SettingsManager._fallback_settings

    # ---------- загрузка / сохранение ----------

    def load_settings(self):
        try:
            if not os.path.exists(self.config_path):
                logger.info("Файл настроек не найден – используем дефолты")
                return

            with open(self.config_path, "r", encoding="utf-8") as f:
                self.settings = json.load(f)
            logger.info("Настройки загружены")

        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"Не удалось загрузить настройки: {e}")
            self.settings = {}

    # Вызывается из фонового потока
    def _write_file(self):
        tmp_path = self.config_path + ".tmp"
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)

        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.settings, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())          # на случай краха ОС

        os.replace(tmp_path, self.config_path)  # атомарно
        logger.debug("Настройки сохранены")

    # ---------- очередь сохранений ----------

    def _schedule_save(self):
        # просто кладём маркер (неважно, какой). Если очередь уже полна – ничего.
        try:
            self._save_queue.put_nowait(1)
        except queue.Full:
            pass

    def save_settings(self):
        """
        Совместимость со старым кодом.
        Фактически просто планируем сохранение через очередь.
        """
        self._schedule_save()

    @staticmethod
    def save():
        """Статический аналог, если где-то вызывают SettingsManager.save()."""
        inst = SettingsManager.instance
        if inst:
            inst._schedule_save()

    def _save_worker(self):
        """
        Берём из очереди, ждём SAVE_DEBOUNCE_SEC,
        если в очереди добавились ещё элементы – игнорируем (они уже учтены),
        затем вызываем _write_file().
        """
        while True:
            item = self._save_queue.get()
            if item is SettingsManager._SENTINEL:
                break            # завершение

            # ждём, пока не иссякнет поток событий
            try:
                while True:
                    self._save_queue.get(timeout=self.SAVE_DEBOUNCE_SEC)
            except queue.Empty:
                pass

            try:
                self._write_file()
            except Exception as e:
                logger.error(f"Ошибка сохранения настроек: {e}")

    def _stop_writer(self):
        # посылаем сигнал, ждём поток и финально сохраняем
        self._save_queue.put(SettingsManager._SENTINEL)
        self._writer_thread.join(timeout=1)
        try:
            self._write_file()
        except Exception as e:
            logger.error(f"Ошибка финального сохранения настроек: {e}")


# ────────────────────────────────────────────────────
# универсальный маленький помощник-иконки
def _angle_icon(kind: str, size: int = 10):
    """kind: 'right' | 'down'"""
    if qta is not None:
        # Chevrons read more clearly as "expandable / expanded" than thin angles.
        name = 'fa6s.chevron-right' if kind == 'right' else 'fa6s.chevron-down'
        try:
            return qta.icon(name, color='#ff9ed3').pixmap(size, size)
        except Exception:
            pass

    app = QApplication.instance()
    if app is not None:
        style = app.style()
        if style is not None:
            standard_pix = (
                QStyle.StandardPixmap.SP_ArrowRight
                if kind == 'right'
                else QStyle.StandardPixmap.SP_ArrowDown
            )
            try:
                return style.standardIcon(standard_pix).pixmap(size, size)
            except Exception:
                pass

    return QPixmap(size, size)
# ────────────────────────────────────────────────────


class CollapsibleSection(QWidget):
    """Внешняя секция"""
    def __init__(self, title, parent=None, *, icon_name=None, subtitle=None):
        super().__init__(parent)
        self.setObjectName('CollapsibleSection')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.is_collapsed = True

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Header
        self.header = QWidget(self, objectName='CollapsibleHeader')

        h = QHBoxLayout(self.header)
        h.setContentsMargins(16, 12, 16, 12)
        h.setSpacing(10)

        self.arrow_label = QLabel(self.header)
        self.arrow_label.setObjectName('CollapsibleArrow')
        self.arrow_pix_right = _angle_icon('right', 13)
        self.arrow_pix_down  = _angle_icon('down',  13)
        self.arrow_label.setPixmap(self.arrow_pix_right)
        self.arrow_label.setFixedWidth(18)
        self.arrow_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Category icon goes *before* the title (left of it), not pinned to the
        # far right where it used to render as a cropped sliver.
        self.icon_label = self._make_icon(icon_name) if icon_name else None

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(2)

        self.title_label = QLabel(title, self.header, objectName='CollapsibleTitle')
        title_col.addWidget(self.title_label)

        self.subtitle_label = None
        subtitle_text = str(subtitle or "").strip()
        if subtitle_text:
            self.subtitle_label = QLabel(subtitle_text, self.header, objectName='CollapsibleSubtitle')
            self.subtitle_label.setWordWrap(True)
            title_col.addWidget(self.subtitle_label)

        if self.icon_label is not None:
            h.addWidget(self.icon_label)
        h.addLayout(title_col, 1)
        h.addStretch()
        h.addWidget(self.arrow_label)

        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.mousePressEvent = self.toggle

        # Content
        self.content_frame = QWidget(self, objectName='CollapsibleContent')
        self.content_layout = QVBoxLayout(self.content_frame)
        self.content_layout.setContentsMargins(20, 8, 20, 16)
        self.content = self.content_frame

        v.addWidget(self.header)
        v.addWidget(self.content_frame)
        self.content_frame.hide()
        self._apply_state_properties()

    def _make_icon(self, name):
        lbl = QLabel(self.header)
        lbl.setObjectName('CollapsibleIcon')
        lbl.setPixmap(qta.icon(name, color='#ffd2ec').pixmap(14, 14) if qta is not None else QPixmap(14, 14))
        lbl.setFixedSize(26, 26)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return lbl

    def toggle(self, _=None):
        self.is_collapsed = not self.is_collapsed
        self.content_frame.setVisible(not self.is_collapsed)
        self.arrow_label.setPixmap(self.arrow_pix_right if self.is_collapsed else self.arrow_pix_down)
        self._apply_state_properties()

    def _apply_state_properties(self):
        expanded = not self.is_collapsed
        for widget in (self, self.header, self.content_frame):
            try:
                widget.setProperty("expanded", expanded)
                style = widget.style()
                if style is not None:
                    style.unpolish(widget)
                    style.polish(widget)
                widget.update()
            except Exception:
                pass

    # --- API ---
    def collapse(self):
        if not self.is_collapsed:
            self.toggle()

    def expand(self):
        if self.is_collapsed:
            self.toggle()
    
    def add_widget(self, w):
        self.content_layout.addWidget(w)
        if self.is_collapsed:
            self.content_frame.hide()



class InnerCollapsibleSection(CollapsibleSection):
    """Под-секция: кликабельный текст без фона"""
    def __init__(self, title, parent=None):
        super().__init__(title, parent)
        self.is_collapsed = True
        self.header.setObjectName('InnerCollapsibleHeader')
        self.header.setStyleSheet('background: transparent;')
        self.arrow_pix_right = _angle_icon('right', 8)
        self.arrow_pix_down  = _angle_icon('down',  8)
        self.arrow_label.setPixmap(self.arrow_pix_right)
        self.header.layout().setContentsMargins(4, 6, 4, 6)
        self.header.layout().setSpacing(4)
        self.arrow_label.setFixedWidth(12) 
        self.title_label.setStyleSheet('font-size:9pt;')
        self.content_layout.setContentsMargins(28, 5, 12, 5)
