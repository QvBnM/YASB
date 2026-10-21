from pydantic import Field

from core.validation.widgets.base_model import CustomBaseModel


class WindowFixConfig(CustomBaseModel):
    class_name: str = ""
    # how often the foreground window is checked (ms)
    interval: int = Field(default=400, ge=150, le=5000)
    # only these processes (e.g. ["Discord.exe", "qbittorrent.exe"]); empty = every maximized window
    processes: list[str] = []
    # never touch these
    exclude: list[str] = ["explorer.exe", "ShellExperienceHost.exe", "SearchHost.exe", "StartMenuExperienceHost.exe"]
    # Aplicatiile scrise aici nu primesc tot ecranul la fullscreen: fereastra lor incepe sub
    # bara, iar bara ramane deasupra. Implicit, lista e goala — fullscreen inseamna fullscreen,
    # bara trece in spate, ca la jocuri.
    #
    # Lista nu e goala degeaba: Chrome (si altele ca el) isi pun fereastra inapoi pe tot ecranul
    # imediat ce o mutam, asa ca ramanea tot peste ecran, doar cu bara deasupra ei — adica
    # fix ce nu voiai. Pune aici un program doar daca vrei anume ca bara sa stea peste el.
    fullscreen_fit: list[str] = []
    # any other fullscreen window (games) covers the bar, like before; it comes back when the game
    # leaves fullscreen, is minimized or closed
    hide_in_fullscreen_games: bool = True
    # re-register the bar when Windows forgets the space it reserves (known Windows 11 bug after
    # fullscreen apps / games: maximized windows then slide under the bar and the taskbar)
    guard_reserved_space: bool = True
    # pixels a window may stick out before it is corrected
    tolerance: int = Field(default=2, ge=0, le=50)
