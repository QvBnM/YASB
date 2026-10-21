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
    # fullscreen (F11, video) of these apps starts just below the bar instead of under it;
    # games are left alone (moving a game's window can break it): the bar simply stays on top
    fullscreen_fit: list[str] = [
        "chrome.exe",
        "msedge.exe",
        "firefox.exe",
        "brave.exe",
        "opera.exe",
        "vivaldi.exe",
        "vlc.exe",
        "mpv.exe",
        "mpc-hc64.exe",
        "mpc-be64.exe",
        "PotPlayerMini64.exe",
        "Video.UI.exe",
    ]
    # any other fullscreen window (games) covers the bar, like before; it comes back when the game
    # leaves fullscreen, is minimized or closed
    hide_in_fullscreen_games: bool = True
    # re-register the bar when Windows forgets the space it reserves (known Windows 11 bug after
    # fullscreen apps / games: maximized windows then slide under the bar and the taskbar)
    guard_reserved_space: bool = True
    # pixels a window may stick out before it is corrected
    tolerance: int = Field(default=2, ge=0, le=50)
