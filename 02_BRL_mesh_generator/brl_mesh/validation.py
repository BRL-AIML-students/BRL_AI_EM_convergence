"""Small internal verdicts; no scoring, report or UI representation."""
from dataclasses import dataclass
from typing import Literal

from .errors import MeshBlocked


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    status: Literal['blocked', 'incomplete'] = 'blocked'


def require_pass(issues: tuple[Issue, ...]) -> None:
    if issues:
        message = '; '.join(f'{x.code}: {x.message}' for x in issues[:3])
        if len(issues) > 3:
            message += f'; 외 {len(issues) - 3}개 차단 사유'
        raise MeshBlocked(message)
