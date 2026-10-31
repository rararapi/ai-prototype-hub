"""Bounded pre-start port selection, outside Windows' common ephemeral range.

The listeners reserve both candidates until the pair is selected, then close before
Docker starts. This is a free-port check, not an OS-wide reservation: exclusions or
another process can still make the later Docker publish fail explicitly.
"""

import random
import socket
from collections.abc import Callable
from contextlib import ExitStack

PORT_MIN = 20_000
PORT_MAX = 29_999
MAX_CANDIDATES = 128


class PortSelectionError(RuntimeError):
    """No usable pair was found within the bounded candidate budget."""


def choose_fixture_ports(
    *,
    max_candidates: int = MAX_CANDIDATES,
    candidate: Callable[[int, int], int] | None = None,
) -> tuple[int, int]:
    """Choose distinct loopback console/preview ports before creating resources."""
    if type(max_candidates) is not int or not 1 <= max_candidates <= 1024:
        raise ValueError("Port selection needs a candidate budget between 1 and 1024")
    draw = candidate or random.SystemRandom().randint
    selected: list[int] = []
    with ExitStack() as listeners:
        for _ in range(max_candidates):
            port = draw(PORT_MIN, PORT_MAX)
            if type(port) is not int or not PORT_MIN <= port <= PORT_MAX:
                raise ValueError("Port candidate is outside the fixture range 20000-29999")
            if port in selected:
                continue
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                listener.bind(("127.0.0.1", port))
            except OSError:
                listener.close()
                continue
            listeners.enter_context(listener)
            selected.append(port)
            if len(selected) == 2:
                return selected[0], selected[1]
    raise PortSelectionError(
        "Could not find two free loopback ports in 20000-29999 after "
        f"{max_candidates} candidates; check occupied or host-reserved ports. "
        "No runtime fixture was started."
    )
