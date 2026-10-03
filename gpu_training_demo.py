"""Train a small model on CUDA and display its real loss in Qtqdm."""

import argparse
from time import sleep
from datetime import datetime
from pathlib import Path

import torch
from torch import nn

from qtqdm import Qtqdm
from training_checkpoint import load_checkpoint, save_checkpoint


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--steps", type=int, help="Total target steps, including steps before resume")
    parser.add_argument("--step-delay", type=float, default=0.03)
    parser.add_argument("--resume", type=Path, help="Resume from a saved .pt training checkpoint")
    args = parser.parse_args()
    if (args.steps is not None and args.steps <= 0) or not 0 <= args.step_delay < float("inf"):
        parser.error("steps must be positive and step-delay must be finite and non-negative")

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable. This demo requires the NVIDIA GPU.")

    device = torch.device("cuda:0")
    torch.manual_seed(42)

    # The model learns to add the eight numbers in each input row.
    inputs = torch.randn(4096, 8, device=device)
    targets = inputs.sum(dim=1, keepdim=True)
    model = nn.Linear(8, 1).to(device)
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    criterion = nn.MSELoss()
    next_step = 0
    target_steps = args.steps if args.steps is not None else 1000
    if args.resume:
        saved = load_checkpoint(args.resume, model, optimizer)
        next_step = saved["next_step"]
        if args.steps is None:
            target_steps = saved["target_steps"]
        if next_step >= target_steps:
            parser.error("Checkpoint reached the target; use --steps with a larger total")
    with torch.no_grad():
        initial_loss = criterion(model(inputs), targets).item()

    Path("runs").mkdir(exist_ok=True)
    run_path = Path("runs") / f"gpu_training_{datetime.now():%Y%m%d_%H%M%S_%f}"
    csv_path = run_path.with_suffix(".csv")
    console_path = run_path.with_suffix(".log")
    checkpoint_path = run_path.with_suffix(".pt")
    progress = Qtqdm(
        range(next_step, target_steps), description="RTX 5060 training demo",
        total=target_steps, initial=next_step,
        open_browser=not args.no_browser, csv_path=csv_path, console_path=console_path,
    )
    progress.control.report_learning_rate(optimizer.param_groups[0]["lr"])

    def save_now():
        name = f"{run_path.name}_step_{next_step:06d}_{datetime.now():%H%M%S_%f}.pt"
        path = run_path.with_name(name)
        save_checkpoint(path, model, optimizer, next_step, target_steps)
        print(f"Checkpoint saved: {path.resolve()}", flush=True)
        return path.resolve()

    progress.control.enable_saving(save_now)
    try:
        with progress:
            print(f"PyTorch: {torch.__version__}; CUDA: {torch.version.cuda}")
            print(f"GPU: {torch.cuda.get_device_name(device)}")
            print(f"Initial step: {next_step}; target: {target_steps}")
            for step in progress:
                new_rate = progress.control.take_learning_rate()
                if new_rate is not None:
                    for group in optimizer.param_groups:
                        group["lr"] = new_rate
                    progress.control.report_learning_rate(new_rate)
                    print(f"Learning rate applied: {new_rate}", flush=True)
                prediction = model(inputs)
                loss = criterion(prediction, targets)
                if not torch.isfinite(loss).item():
                    raise RuntimeError("Loss became non-finite; check the learning rate")
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                next_step = step + 1
                progress.set_postfix(loss=loss.item(), learning_rate=optimizer.param_groups[0]["lr"])
                if next_step % 25 == 0 or next_step == target_steps:
                    print(f"Step {next_step}/{target_steps} | loss={loss.item():.6g} | lr={optimizer.param_groups[0]['lr']}", flush=True)
                if args.step_delay:
                    sleep(args.step_delay)

            with torch.no_grad():
                final_loss = criterion(model(inputs), targets).item()
            torch.cuda.synchronize()
            if not torch.isfinite(torch.tensor(final_loss)).item():
                raise RuntimeError("Final loss is non-finite; check the learning rate")
            save_checkpoint(checkpoint_path, model, optimizer, next_step, target_steps)
            print(f"Model device: {next(model.parameters()).device}")
            print(f"Loss: {initial_loss:.8f} -> {final_loss:.8f}")
            print(f"CSV: {csv_path.resolve()}")
            print(f"Console log: {console_path.resolve()}")
            print(f"Task state: {progress.state}")
            print(f"Checkpoint: {checkpoint_path.resolve()}")
            print(f"Saved next step: {next_step}; learning rate: {optimizer.param_groups[0]['lr']}")
    finally:
        if args.keep_open:
            progress.wait()
        else:
            progress.close()


if __name__ == "__main__":
    main()
