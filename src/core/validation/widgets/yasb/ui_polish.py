from pydantic import Field

from core.validation.widgets.base_model import CustomBaseModel

DEFAULT_STRINGS: dict[str, str] = {
    # Wi-Fi (YASB)
    "WiFi Networks": "Wi-Fi",
    "More Wi-Fi settings": "Setări Wi-Fi",
    "Connected, Secured": "Conectat",
    "Connected": "Conectat",
    "Secured": "Securizată",
    "Unsecured": "Deschisă",
    "Connect": "Conectează",
    "Disconnect": "Deconectează",
    "Wi-Fi is not available": "Wi-Fi nu e disponibil",
    "Error: WiFi adapter is disabled...": "Placa Wi-Fi e oprită",
    "Error: Location services are disabled...": "Pornește Locația din Setări ca să vezi rețelele",
    # Calendar (YASB)
    "Set Alarm": "Alarmă",
    "Set Timer": "Cronometru",
    "Upcoming holidays": "Sărbători legale",
    "Weekdays": "Zile lucrătoare",
    # Pomodoro (YASB)
    "Reset": "Resetează",
    "Skip": "Sari peste",
}


class PatternRule(CustomBaseModel):
    pattern: str
    replacement: str


DEFAULT_PATTERNS = [
    PatternRule(pattern=r"^Week (\d+)$", replacement=r"Săptămâna \1"),
    PatternRule(pattern=r"^Session: (.+)$", replacement=r"Sesiunea \1"),
]


class CalendarPolishConfig(CustomBaseModel):
    enabled: bool = True
    country_code: str = "RO"
    weekend_color: str = "accent2"  # nume de variabila din palette.css
    outside_color: str = "muted"  # zilele din luna dinainte / de dupa
    holiday_color: str = "danger"  # inlocuieste holiday_color scris de mana in config
    full_holiday_names: bool = True
    next_holiday: bool = True
    next_holiday_format: str = "Următoarea liberă:\n{name}, {when}"


class UiPolishConfig(CustomBaseModel):
    strings: dict[str, str] = DEFAULT_STRINGS
    extra_strings: dict[str, str] = {}  # se adauga peste cele implicite
    patterns: list[PatternRule] = DEFAULT_PATTERNS
    calendar: CalendarPolishConfig = CalendarPolishConfig()
    max_label_scan: int = Field(default=400, ge=50)
