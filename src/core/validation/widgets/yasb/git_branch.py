from pydantic import Field

from core.validation.widgets.base_model import CallbacksConfig, CustomBaseModel


class GitBranchCallbacksConfig(CallbacksConfig):
    on_left: str = "toggle_label"


class GitBranchConfig(CustomBaseModel):
    # {branch} {ahead} {behind} {changes} ; {sync} = "↑2 ↓1" sau gol ; {dirty} = "~3" sau gol
    label: str = "<span></span> {branch}<span class='unit'>{sync}{dirty}</span>"
    label_alt: str = "<span></span> {repo}: {branch}"
    class_name: str = ""
    roots: list[str] = []  # foldere in care stau repo-urile (cautare pe 2 niveluri)
    editors: list[str] = ["Code.exe", "Cursor.exe", "VSCodium.exe"]
    keep_last: bool = True  # ramane pe ultimul repo cand treci in browser, pana deschizi alt editor
    update_interval: int = Field(default=3000, ge=1000)
    callbacks: GitBranchCallbacksConfig = GitBranchCallbacksConfig()
