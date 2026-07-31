from __future__ import annotations

import random
import time


def pause(minimum: float, maximum: float) -> None:
    time.sleep(random.uniform(minimum, maximum))


def type_with_variation(sb, selector: str, text: str) -> None:
    """Type at variable speed without altering browser identity or page security state."""
    sb.cdp.click(selector)
    for char in text:
        sb.cdp.type(selector, char)
        time.sleep(random.uniform(0.05, 0.2))


def read_pause(minimum: int = 15, maximum: int = 45) -> None:
    pause(minimum, maximum)

