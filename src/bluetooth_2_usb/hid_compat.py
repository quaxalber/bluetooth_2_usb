from __future__ import annotations

from inspect import Parameter, signature
from typing import Any


def _required_positional_count(method: Any) -> int | None:
    try:
        parameters = signature(method).parameters.values()
    except (TypeError, ValueError):
        return None
    return sum(
        1
        for parameter in parameters
        if parameter.default is Parameter.empty
        and parameter.kind
        in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD)
    )


def release_consumer_control(consumer: Any) -> None:
    required_args = _required_positional_count(consumer.release)
    if required_args == 0:
        consumer.release()
    elif required_args == 1:
        consumer.release(0)
    else:
        consumer.release()
