# Upstream source

Source: [HAN-oQo/RL_for_2048](https://github.com/HAN-oQo/RL_for_2048)

Pinned commit: `44b4825de89fd6e4beaf2f567b81b9673f0a1921`.

Retrieved on 2026-10-03. DQN agent, networks, replay buffer and environment are copied from this commit. `env.py` comes from upstream `gym_2048/env.py`. The environment acknowledges [activatedgeek/gym-2048](https://github.com/activatedgeek/gym-2048); both MIT notices are retained in `License` and `GYM_LICENSE`.

## Local changes

- Headless/text environment only; remove Pygame rendering and global Gymnasium registration. Gymnasium is the only new direct dependency.
- Spawn tiles only after a move changes the board; calculate action masks from actual legal moves, including sparse boards; sample distinct initial tile locations.
- Remove the original invalid-move truncation block; demo explicitly limits episode moves.
- Mask illegal actions with negative infinity, including when all legal Q values are negative; exploration also chooses legal moves.
- Detach target Q values from autograd and use the input device for action indices.
- Store replay observations/rewards as float32 and actions as int64; convert batches directly to the selected device.
- Correct the LeakyReLU spelling and restore target/optimizer in the upstream checkpoint loader.
- Use explicit package exports/imports and consistent indentation; remove unused rendering/debugging imports and comments. Algorithm remains DQN with a soft-updated target network and MSE loss.

`rl2048_demo.py` is a local training adapter. It uses the upstream fully connected network, log2 observations and rewards, move-based epsilon decay and optimizer updates every four moves (configurable). Smaller replay/batch/warmup defaults suit a short local demo. These differ from upstream's episode-based training defaults; reported upstream scores are not our benchmark results.

`rl2048_checkpoint.py` adds complete training checkpoints. The upstream W&B/Docker/video scripts and pretrained models are not used.
