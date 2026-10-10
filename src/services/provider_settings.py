from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from presets.api_protocols import API_PROTOCOLS_DATA
from utils import _


@dataclass(frozen=True)
class ProviderSettings:
    api_url: bool = True
    api_key: bool = True
    reserve_keys: bool = True
    generation_parameters: bool = True


@dataclass(frozen=True)
class ProviderDescriptor:
    provider: str
    authentication: str
    connection_action: str = 'test_connection'
    action_label: tuple[str, str] = ('Проверить', 'Check')
    settings: ProviderSettings = field(default_factory=ProviderSettings)
    account_actions: bool = False
    subscription_notice: tuple[str, str] = ('', '')
    usage_dashboard_url: str = ''


class AuthenticationService(Protocol):
    def status(self) -> dict[str, Any]: ...
    def sign_in(self, **kwargs) -> dict[str, Any]: ...
    def sign_out(self) -> dict[str, Any]: ...
    def list_models(self) -> list[dict[str, str]]: ...
    def list_accounts(self) -> list[dict[str, Any]]: ...
    def select_account(self, account_id: str) -> dict[str, Any]: ...


_AUTH_DESCRIPTORS = {
    'oauth_chatgpt': {
        'connection_action': 'sign_in',
        'action_label': ('Войти через ChatGPT', 'Continue with ChatGPT'),
        'settings': ProviderSettings(False, False, False, True),
        'account_actions': True,
        'subscription_notice': (
            'Экспериментальный режим. Запросы используют вашу квоту ChatGPT/Codex. Доступность моделей и лимиты зависят от аккаунта. Управление использованием — в ChatGPT.',
            'Experimental mode. Requests use your ChatGPT/Codex allowance. Model availability and limits depend on your account. Manage usage in ChatGPT.',
        ),
        'usage_dashboard_url': 'https://chatgpt.com/settings/usage',
    },
}


def describe_protocol(protocol_id: str) -> ProviderDescriptor:
    proto = next((p for p in API_PROTOCOLS_DATA if p['id'] == protocol_id), {})
    mode = str((proto.get('auth') or {}).get('mode') or 'none')
    return ProviderDescriptor(str(proto.get('provider') or ''), mode, **_AUTH_DESCRIPTORS.get(mode, {}))


def authentication_service(protocol_id: str) -> AuthenticationService:
    descriptor = describe_protocol(protocol_id)
    if descriptor.authentication == 'oauth_chatgpt':
        from handlers.llm_providers.chatgpt_plan_auth import get_chatgpt_plan_auth
        return get_chatgpt_plan_auth()
    raise ValueError('This provider has no account authentication service')


def run_account_action(protocol_id: str, action: str, account_id: str = '') -> dict[str, Any]:
    auth = authentication_service(protocol_id)
    if action == 'sign_out':
        result = auth.sign_out()
        return {'success': True, 'account': result, 'message': _(
            'Выход выполнен.', 'Signed out.') if result.get('revoked') else _(
            'Выход выполнен локально; отзыв сессии на сервере не подтверждён.',
            'Signed out locally; remote session revocation was not confirmed.')}
    if action == 'select_account':
        auth.select_account(account_id)
    elif action == 'add_account':
        auth.sign_in(new_account=True)
    elif action == 'sign_in':
        auth.sign_in()
    elif action != 'list_models':
        raise ValueError('Unknown account action')
    status = auth.status()
    if not status.get('plan_usage_enabled', True):
        return {'success': action != 'list_models', 'account': status, 'models': [], 'message': _(
            'Аккаунт подключён, но использование плана ChatGPT не разрешено. Войдите через ChatGPT повторно, чтобы включить его.',
                    'Account connected, but ChatGPT plan usage is disabled. Sign in with ChatGPT again to enable it.')}
    notice = getattr(auth, 'consume_plan_usage_notice', None)
    show_notice = bool(action != 'list_models' and callable(notice) and notice())
    try:
        models = auth.list_models()
    except Exception:
        status = auth.status()
        return {'success': action != 'list_models' and bool(status.get('signed_in')), 'account': status, 'models': [],
                'show_plan_usage_notice': show_notice,
                'catalog_error': True, 'message': _(
                    'Не удалось обновить список моделей. Состояние аккаунта сохранено. Повторите «Получить модели».',
                    'Could not refresh the model catalog. Account state was retained. Try Load models again.')}
    status = auth.status()
    return {'success': True, 'message': _(
        'Аккаунт: {email}. Найдено моделей: {count}',
        'Account: {email}. Models found: {count}').format(email=status.get('email') or '', count=len(models)),
        'models': [m['id'] for m in models], 'model_infos': models, 'account': status,
        'show_plan_usage_notice': show_notice}


def list_provider_accounts(protocol_id: str) -> list[dict[str, Any]]:
    return authentication_service(protocol_id).list_accounts()
