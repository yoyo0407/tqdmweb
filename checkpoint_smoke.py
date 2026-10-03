"""Stronger GPU smoke test: stochastic MLP, BatchNorm and AdamW resume."""

import os

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

from pathlib import Path
from tempfile import TemporaryDirectory

import torch
from torch import nn

from training_checkpoint import load_checkpoint, save_checkpoint


def build(device):
    model = nn.Sequential(
        nn.Linear(64, 128), nn.BatchNorm1d(128), nn.ReLU(), nn.Dropout(0.25),
        nn.Linear(128, 64), nn.ReLU(), nn.Dropout(0.15), nn.Linear(64, 4),
    ).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.003, weight_decay=0.01)
    return model, optimizer


def train(model, optimizer, inputs, labels, count):
    model.train()
    losses = []
    for _ in range(count):
        # Random batches and Dropout both depend on the CUDA RNG state.
        indices = torch.randint(len(inputs), (128,), device=inputs.device)
        loss = nn.functional.cross_entropy(model(inputs[indices]), labels[indices])
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        losses.append(loss.item())
    return losses


def main():
    if not torch.cuda.is_available():
        raise RuntimeError("This smoke test requires the NVIDIA GPU")
    torch.use_deterministic_algorithms(True)
    device = torch.device("cuda:0")
    print(f"GPU: {torch.cuda.get_device_name(device)}", flush=True)
    torch.manual_seed(123)
    inputs = torch.randn(4096, 64, device=device)
    teacher = torch.randn(64, 4, device=device)
    labels = (inputs @ teacher).argmax(dim=1)
    model, optimizer = build(device)

    with TemporaryDirectory() as directory:
        path = Path(directory) / "adamw_dropout.pt"
        first_losses = train(model, optimizer, inputs, labels, 60)
        save_checkpoint(path, model, optimizer, 60, 120)
        expected_losses = train(model, optimizer, inputs, labels, 60)
        expected_model = {key: value.clone() for key, value in model.state_dict().items()}
        expected_optimizer = optimizer.state_dict()

        resumed_model, resumed_optimizer = build(device)
        metadata = load_checkpoint(path, resumed_model, resumed_optimizer)
        assert metadata == {"next_step": 60, "target_steps": 120}
        resumed_losses = train(resumed_model, resumed_optimizer, inputs, labels, 60)
        for key, value in resumed_model.state_dict().items():
            assert torch.equal(value, expected_model[key]), f"Model mismatch: {key}"
        for parameter, state in resumed_optimizer.state_dict()["state"].items():
            for name, value in state.items():
                expected = expected_optimizer["state"][parameter][name]
                if isinstance(value, torch.Tensor):
                    assert torch.equal(value, expected), f"Optimizer mismatch: {name}"
                else:
                    assert value == expected
        assert resumed_losses == expected_losses, "Resumed loss sequence differs"
        assert sum(expected_losses[-10:]) < sum(first_losses[:10]), "Training did not improve"
        print(f"PASS: 120 steps; {sum(p.numel() for p in model.parameters()):,} parameters", flush=True)
        print("PASS: model weights, BatchNorm buffers, AdamW moments and per-step loss match exactly", flush=True)
        print(f"Mean loss: {sum(first_losses[:10])/10:.4f} -> {sum(expected_losses[-10:])/10:.4f}", flush=True)
        print(f"Checkpoint size: {path.stat().st_size:,} bytes", flush=True)


if __name__ == "__main__":
    main()
