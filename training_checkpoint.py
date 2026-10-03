"""Save and restore training state; independent of the monitoring page."""

from pathlib import Path

import torch


def save_checkpoint(path, model, optimizer, next_step, target_steps):
    device = next(model.parameters()).device
    state = {
        "format_version": 1,
        "model": model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "next_step": next_step,
        "target_steps": target_steps,
        "cpu_rng_state": torch.get_rng_state(),
        "cuda_rng_state": torch.cuda.get_rng_state(device) if device.type == "cuda" else None,
    }
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        torch.save(state, temporary)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_checkpoint(path, model, optimizer):
    state = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(state, dict) or state.get("format_version") != 1:
        raise ValueError("Unsupported training checkpoint format")
    required = {"model", "optimizer", "next_step", "target_steps", "cpu_rng_state", "cuda_rng_state"}
    if not required.issubset(state):
        raise ValueError("Incomplete training checkpoint")
    step, target = state["next_step"], state["target_steps"]
    if type(step) is not int or type(target) is not int or not 0 <= step <= target:
        raise ValueError("Invalid checkpoint step numbers")

    model.load_state_dict(state["model"])
    optimizer.load_state_dict(state["optimizer"])
    torch.set_rng_state(state["cpu_rng_state"])
    device = next(model.parameters()).device
    if device.type == "cuda" and state["cuda_rng_state"] is not None:
        torch.cuda.set_rng_state(state["cuda_rng_state"], device)
    return {"next_step": step, "target_steps": target}
