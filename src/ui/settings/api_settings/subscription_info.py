from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout

from localization.live import register
from styles.theme import THEME
from utils import _


class SubscriptionInfo(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName('ApiSubscriptionInfo')
        self.setStyleSheet(
            f'QFrame#ApiSubscriptionInfo {{ border: 1px solid {THEME["panel_border"]}; '
            'border-radius: 10px; }'
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        register(self.notice, self._refresh_notice)
        self.dashboard_link = QLabel()
        self.dashboard_link.setObjectName('LinkLabel')
        self.dashboard_link.setOpenExternalLinks(True)
        register(self.dashboard_link, self._refresh_link)
        layout.addWidget(self.dashboard_link)
        self.hide()

    @staticmethod
    def _refresh_notice(label):
        label.setText(_(*(label.property('noticeText') or ('', ''))))

    @staticmethod
    def _refresh_link(label):
        label.setText(
            f'<a href="{label.property("dashboardUrl") or ""}" style="color: {THEME["link"]};">'
            + str(_('Управление использованием ChatGPT', 'Manage ChatGPT usage')) + '</a>'
        )

    def configure(self, descriptor):
        self.notice.setProperty('noticeText', descriptor.subscription_notice)
        self._refresh_notice(self.notice)
        self.dashboard_link.setProperty('dashboardUrl', descriptor.usage_dashboard_url)
        self._refresh_link(self.dashboard_link)
        self.setVisible(bool(descriptor.usage_dashboard_url))
