"""Validate the SGD demo's restart hyperparameters without importing PyTorch."""

from math import isfinite


DEFAULT_PARAMETERS = {"learning_rate": 0.1, "momentum": 0.0,
                      "weight_decay": 0.0, "target_steps": 1000}


def validate_parameters(parameters):
    if set(parameters) != set(DEFAULT_PARAMETERS):
        raise ValueError("Expected learning_rate, momentum, weight_decay and target_steps")
    result = {}
    for name in ("learning_rate", "momentum", "weight_decay"):
        value = parameters[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
            raise ValueError(f"{name} must be a finite number")
        result[name] = float(value)
    if result["learning_rate"] <= 0:
        raise ValueError("learning_rate must be greater than zero")
    if not 0 <= result["momentum"] < 1:
        raise ValueError("momentum must be in [0, 1)")
    if result["weight_decay"] < 0:
        raise ValueError("weight_decay must be non-negative")
    steps = parameters["target_steps"]
    if type(steps) is not int or steps <= 0:
        raise ValueError("target_steps must be a positive integer")
    result["target_steps"] = steps
    return result
