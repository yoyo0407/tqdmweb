"""Run the public HAN-oQo 2048 DQN through Qtqdm on the local CUDA GPU."""

import argparse
from collections import deque
from datetime import datetime
from math import exp, isfinite
import os
from pathlib import Path
from time import sleep

import numpy as np
import torch

from qtqdm import Qtqdm
import rl2048_checkpoint as checkpoint
from third_party.rl2048.dqn import DQN, ReplayBuffer
from third_party.rl2048.env import Base2048Env


def encode(board):
    # Empty cells become 0; tile values become their base-2 exponent.
    return np.log2(np.maximum(board, 1)).astype(np.float32).flatten()


def train(args):
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; this demo requires the NVIDIA GPU")
    device = torch.device("cuda:0")
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    env = Base2048Env()
    env.reset(seed=args.seed)
    config = {"architecture": "linear", "hidden_layer": 4, "hidden_units": 256,
              "non_linearity": "ReLU", "learning_rate": {"policy": args.learning_rate},
              "discount": 0.99, "target_smoothing_coefficient": 0.005}
    agent = DQN(16, 4, config).to(device)
    memory = ReplayBuffer(args.buffer_size, 16, 1)
    state = {"next_step": 0, "episode": 1, "episode_moves": 0, "score": 0,
             "best_tile": int(env.board.max()), "updates": 0, "scores": [], "loss": None,
             "batch_size": args.batch_size, "warmup": args.warmup, "train_every": args.train_every,
             "epsilon_decay": args.epsilon_decay, "max_episode_moves": args.max_episode_moves}
    if args.resume:
        state = checkpoint.load(args.resume, agent, memory, env)
    if state["next_step"] >= args.steps:
        raise ValueError("Checkpoint reached the target; choose a larger --steps value")
    scores = deque(state["scores"], maxlen=20)
    run_folder = Path(__file__).resolve().parent / "runs" / "2048"
    run_folder.mkdir(parents=True, exist_ok=True)
    run_path = run_folder / f"dqn_{datetime.now():%Y%m%d_%H%M%S_%f}"
    progress = Qtqdm(range(state["next_step"], args.steps), total=args.steps,
                      initial=state["next_step"], desc="2048 DQN Training",
                      csv_path=run_path.with_suffix(".csv"), console_path=run_path.with_suffix(".log"),
                      open_browser=not args.no_browser)

    def save_now():
        state["scores"] = list(scores)
        path = run_path.with_name(f"{run_path.name}_step_{state['next_step']:06d}_{datetime.now():%H%M%S_%f}.pt")
        result = checkpoint.save(path, agent, memory, env, state)
        print(f"Checkpoint saved: {result}", flush=True)
        return result

    def set_learning_rate(value):
        for group in agent.optimizer.param_groups:
            group["lr"] = value
        print(f"Learning rate applied: {value}", flush=True)

    progress.register_controls(save_checkpoint=save_now, set_learning_rate=set_learning_rate,
                              learning_rate=agent.optimizer.param_groups[0]["lr"])
    try:
        with progress:
            print("Source: HAN-oQo/RL_for_2048 (MIT), commit 44b4825")
            print(f"GPU: {torch.cuda.get_device_name(device)} | Model device: {next(agent.parameters()).device}")
            print(f"Step unit: game move | Target: {args.steps} | Resumed at: {state['next_step']}")
            print("Checkpoint includes policy, target, optimizer, replay buffer, game and RNG state.")
            for step in progress:
                observation = encode(env.board)
                action_mask = torch.tensor(env.is_done()[1], dtype=torch.bool, device=device)
                epsilon = 0.05 + 0.85 * exp(-step / state["epsilon_decay"])
                action = agent.get_action(torch.as_tensor(observation, device=device).unsqueeze(0), epsilon, action_mask)
                _, reward, terminated, _, _ = env.step(action)
                state["episode_moves"] += 1
                truncated = state["episode_moves"] >= state["max_episode_moves"]
                done = terminated or truncated
                memory.put(observation, action, np.log2(reward) if reward else 0.0, encode(env.board), done)
                state["score"] += int(reward)
                state["best_tile"] = max(state["best_tile"], int(env.board.max()))
                state["next_step"] = step + 1
                if memory.size() >= state["warmup"] and (step + 1) % state["train_every"] == 0:
                    batch = ReplayBuffer.batch_to_device(memory.sample(state["batch_size"]), device)
                    loss = agent.train_net(batch)
                    if not isfinite(loss):
                        raise RuntimeError("DQN loss became non-finite; check the learning rate")
                    state["loss"] = loss
                    state["updates"] += 1
                metrics = {"episode": state["episode"], "score": state["score"], "max_tile": int(env.board.max()),
                           "best_tile": state["best_tile"], "epsilon": epsilon, "replay_size": memory.size(),
                           "updates": state["updates"], "learning_rate": agent.optimizer.param_groups[0]["lr"]}
                if state["loss"] is not None:
                    metrics["loss"] = state["loss"]
                if scores:
                    metrics["mean_score_20"] = sum(scores) / len(scores)
                progress.set_postfix(metrics)
                if done or (step + 1) % 250 == 0:
                    print(f"Step {step + 1}/{args.steps} | Episode {state['episode']} | Score {state['score']} | "
                          f"Max tile {int(env.board.max())} | Epsilon {epsilon:.3f} | Loss {state['loss']}", flush=True)
                    env.render_mode = "human"
                    env.render()
                    env.render_mode = None
                if done:
                    scores.append(state["score"])
                    state["episode"] += 1
                    state["episode_moves"] = state["score"] = 0
                    env.reset()
                if args.step_delay:
                    sleep(args.step_delay)
            save_now()
            print(f"Task state: {progress.state} | Optimizer updates: {state['updates']} | Best tile: {state['best_tile']}")
            print(f"CSV: {run_path.with_suffix('.csv')}")
    finally:
        env.close()
        if args.keep_open or os.environ.get("TQDMBOARD") == "1":
            progress.wait()
        else:
            progress.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=20000, help="Total game moves, including resumed moves")
    parser.add_argument("--learning-rate", type=float, default=0.0001)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--buffer-size", type=int, default=20000)
    parser.add_argument("--warmup", type=int, default=256)
    parser.add_argument("--train-every", type=int, default=4)
    parser.add_argument("--epsilon-decay", type=int, default=5000)
    parser.add_argument("--max-episode-moves", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--step-delay", type=float, default=0)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()
    counts = (args.steps, args.batch_size, args.buffer_size, args.warmup, args.train_every,
              args.epsilon_decay, args.max_episode_moves)
    if any(value <= 0 for value in counts) or not args.batch_size <= args.warmup <= args.buffer_size:
        parser.error("Counts must be positive, with batch-size <= warmup <= buffer-size")
    if not isfinite(args.learning_rate) or args.learning_rate <= 0 or not isfinite(args.step_delay) or args.step_delay < 0:
        parser.error("learning-rate must be positive; step-delay must be finite and non-negative")
    if not 0 <= args.seed < 2**32:
        parser.error("seed must be between 0 and 2**32 - 1")
    train(args)


if __name__ == "__main__":
    main()
