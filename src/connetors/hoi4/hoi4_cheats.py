# hoi4_cheats.py
"""
Cheat-обёртка с параметром country_tag.
Работает поверх injector.run_console_cmd().
"""
import time
from hoi4_connector import run_console_cmd          # ваша функция

# ────────── 1.  Определяем / храним текущий TAG игрока ──────────
_current_player_tag: str | None = None

def _detect_player_tag() -> str:
    """
    Запрашиваем у игры командой 'whoami', парсим ответ из game.log.
    Предполагаем, что tailer уже крутится и ловит MITA_OUT строки.
    Самый простой (хакерский) способ – сделать временный файл.
    """
    global _current_player_tag
    # (а) вlog-метод: run_console_cmd("whoami") + ждём ответ в хвосте
    # для краткости – ставим заглушку:
    time.sleep(0.3)
    _current_player_tag = "GER"
    return _current_player_tag

def get_player_tag() -> str:
    global _current_player_tag
    if not _current_player_tag:
        _current_player_tag = _detect_player_tag()
    return _current_player_tag

def set_player_tag(tag: str):
    global _current_player_tag
    _current_player_tag = tag.upper()


# ────────── 2.  Контекст-менеджер для временного switch TAG ─────
from contextlib import contextmanager

@contextmanager
def switch_to(tag: str | None):
    """
    Если tag указан и отличается от текущего – выполняем:
        tag <OTHER>
        …ваши команды…
        tag <BACK>
    Иначе просто выполняем тело контекста.
    """
    tag = tag.upper() if tag else None
    back = get_player_tag()
    need_switch = tag and tag != back
    if need_switch:
        run_console_cmd(f"tag {tag}")
        time.sleep(0.1)
    try:
        yield
    finally:
        if need_switch:
            run_console_cmd(f"tag {back}")
            time.sleep(0.1)


# ────────── 3.  Читы (принимают country=None) ───────────────────
def add_pp(amount: int = 100, country: str | None = None):
    """Добавляет политическую власть. Команда умеет работать с TAG сразу."""
    if country:
        run_console_cmd(f"pp {amount} {country}")
    else:
        run_console_cmd(f"pp {amount}")

def add_stability(amount: int = 10, country: str | None = None):
    if country:
        run_console_cmd(f"st {amount} {country}")
    else:
        run_console_cmd(f"st {amount}")

def add_war_support(amount: int = 10, country: str | None = None):
    if country:
        run_console_cmd(f"ws {amount} {country}")
    else:
        run_console_cmd(f"ws {amount}")

def add_army_xp(amount: int = 50, country: str | None = None):
    # у xp команды нет параметра TAG => делаем switch
    with switch_to(country):
        run_console_cmd(f"xp {amount}")

def add_navy_xp(amount: int = 50, country: str | None = None):
    with switch_to(country):
        run_console_cmd(f"xpnavy {amount}")

def add_air_xp(amount: int = 50, country: str | None = None):
    with switch_to(country):
        run_console_cmd(f"xpair {amount}")

def add_manpower(amount: int = 100_000, country: str | None = None):
    if country:
        run_console_cmd(f"manpower {amount} {country}")
    else:
        run_console_cmd(f"manpower {amount}")

def instant_construction(enable: bool = True):
    run_console_cmd("ic")         # глобальный флаг – без TAG

def focus_autocomplete(enable: bool = True):
    run_console_cmd("focus.nochecks")
    run_console_cmd("focus.autocomplete")

def allow_diplo():
    run_console_cmd("allowdiplo")  # также глобальный

def annex(target_tag: str, actor_tag: str | None = None):
    # annex <target> [actor]; если actor не указан – текущий
    if actor_tag:
        run_console_cmd(f"annex {target_tag} {actor_tag}")
    else:
        run_console_cmd(f"annex {target_tag}")

def whitepeace(tag1: str, tag2: str):
    run_console_cmd(f"whitepeace {tag1} {tag2}")

def civil_war(ideology: str = "communism", country: str | None = None):
    if country:
        run_console_cmd(f"civilwar {ideology} {country}")
    else:
        run_console_cmd(f"civilwar {ideology}")

def research_all(country: str | None = None):
    with switch_to(country):
        run_console_cmd("research all")

def add_factories(state: int, civ: int = 0, mil: int = 0, dock: int = 0,
                  country: str | None = None):
    with switch_to(country):
        if civ:
            run_console_cmd(f"add_building {state} 1 {civ}")
        if mil:
            run_console_cmd(f"add_building {state} 2 {mil}")
        if dock:
            run_console_cmd(f"add_building {state} 3 {dock}")

# ────────── 4.  Диспетчер для нейронки (cmd + params) ───────────
_cheat_map = {
    "add_pp":            lambda p: add_pp(p.get("amount", 100), p.get("country")),
    "add_stability":     lambda p: add_stability(p.get("amount", 10), p.get("country")),
    "add_war_support":   lambda p: add_war_support(p.get("amount", 10), p.get("country")),
    "add_army_xp":       lambda p: add_army_xp(p.get("amount", 50), p.get("country")),
    "add_navy_xp":       lambda p: add_navy_xp(p.get("amount", 50), p.get("country")),
    "add_air_xp":        lambda p: add_air_xp(p.get("amount", 50), p.get("country")),
    "add_manpower":      lambda p: add_manpower(p.get("amount", 100000), p.get("country")),
    "instant_ic":        lambda p: instant_construction(p.get("enable", True)),
    "focus_auto":        lambda p: focus_autocomplete(p.get("enable", True)),
    "allow_diplo":       lambda p: allow_diplo(),
    "annex":             lambda p: annex(p["target"], p.get("actor")),
    "whitepeace":        lambda p: whitepeace(p["tag1"], p["tag2"]),
    "civil_war":         lambda p: civil_war(p.get("ideology", "communism"), p.get("country")),
    "research_all":      lambda p: research_all(p.get("country")),
    "add_factories":     lambda p: add_factories(p["state"], p.get("civ",0),
                                                 p.get("mil",0), p.get("dock",0),
                                                 p.get("country")),
}

def execute_cheat(cmd_name: str, **params):
    func = _cheat_map.get(cmd_name)
    if not func:
        raise ValueError(f"Cheat '{cmd_name}' not supported")
    func(params)


# ────────── 5.  Мини-тест ────────────────────────────────────────
if __name__ == "__main__":
    # даст 250 PP Франции, не трогая игрока
    execute_cheat("add_pp", amount=250, country="FRA")

    # у СССР построит 2 ГОК и 1 верфь в Ленинграде (state 195)
    execute_cheat("add_factories",
                  state=195, civ=0, mil=2, dock=1,
                  country="SOV")

    # вынесет Польшу командой annex (от лица Германии по умолчанию)
    execute_cheat("annex", target="POL")