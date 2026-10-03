"""2048 training state, including the replay buffer and current game."""

import json
from pathlib import Path

import numpy as np
import torch


BUFFER_FIELDS = ("state_memory", "new_state_memory", "action_memory", "reward_memory", "terminal_memory")


def save(path, agent, memory, env, training):
    rng = np.random.get_state()
    size = memory.size()
    state = {
        "format": "qtqdm-2048-v1",
        "agent": agent.state_dict(),
        "optimizer": agent.optimizer.state_dict(),
        "training": training.copy(),
        "replay_capacity": memory.mem_size,
        "replay_count": memory.mem_cntr,
        "replay": {name: torch.from_numpy(getattr(memory, name)[:size].copy()) for name in BUFFER_FIELDS},
        "board": torch.from_numpy(env.board.copy()),
        "env_rng": json.dumps(env.np_random.bit_generator.state),
        "numpy_rng": [rng[0], torch.from_numpy(rng[1].astype(np.int64)), rng[2], rng[3], rng[4]],
        "torch_rng": torch.get_rng_state(),
        "cuda_rng": torch.cuda.get_rng_state(next(agent.parameters()).device)
        if next(agent.parameters()).is_cuda else None,
    }
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        torch.save(state, temporary)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path.resolve()


def load(path, agent, memory, env):
    state = torch.load(path, map_location="cpu", weights_only=True)
    if state.get("format") != "qtqdm-2048-v1":
        raise ValueError("Unsupported 2048 checkpoint")
    if state["replay_capacity"] != memory.mem_size:
        raise ValueError("Resume requires the original replay buffer capacity")
    agent.load_state_dict(state["agent"])
    agent.optimizer.load_state_dict(state["optimizer"])
    memory.mem_cntr = state["replay_count"]
    for name in BUFFER_FIELDS:
        destination = getattr(memory, name)
        destination.fill(0)
        source = state["replay"][name].numpy()
        destination[:len(source)] = source
    env.board = state["board"].numpy().copy()
    env.np_random.bit_generator.state = json.loads(state["env_rng"])
    rng = state["numpy_rng"]
    np.random.set_state((rng[0], rng[1].numpy().astype(np.uint32), rng[2], rng[3], rng[4]))
    torch.set_rng_state(state["torch_rng"])
    device = next(agent.parameters()).device
    if device.type == "cuda" and state["cuda_rng"] is not None:
        torch.cuda.set_rng_state(state["cuda_rng"], device)
    return state["training"]
