"""Train a small model on CUDA and display its real loss in Qtqdm."""

import argparse
from time import sleep
from datetime import datetime
from pathlib import Path

import torch
from torch import nn

from qtqdm.session import TrainingSession
from training_config import validate_parameters
from training_checkpoint import load_checkpoint, save_checkpoint


def train_run(session, parameters, resume_path=None, override_steps=False, step_delay=0.03):
    device = torch.device("cuda:0")
    torch.manual_seed(42)

    # The model learns to add the eight numbers in each input row.
    inputs = torch.randn(4096, 8, device=device)
    targets = inputs.sum(dim=1, keepdim=True)
    model = nn.Linear(8, 1).to(device)
    optimizer = torch.optim.SGD(model.parameters(), lr=parameters["learning_rate"],
                                momentum=parameters["momentum"], weight_decay=parameters["weight_decay"])
    criterion = nn.MSELoss()
    next_step = 0
    target_steps = parameters["target_steps"]
    if resume_path is not None and session.run_attempt == 1:
        saved = load_checkpoint(resume_path, model, optimizer)
        next_step = saved["next_step"]
        if not override_steps:
            target_steps = saved["target_steps"]
        if next_step >= target_steps:
            raise ValueError("Checkpoint reached the target; use --steps with a larger total")
    with torch.no_grad():
        initial_loss = criterion(model(inputs), targets).item()

    Path("runs").mkdir(exist_ok=True)
    run_path = Path("runs") / f"gpu_training_{datetime.now():%Y%m%d_%H%M%S_%f}"
    csv_path = run_path.with_suffix(".csv")
    console_path = run_path.with_suffix(".log")
    checkpoint_path = run_path.with_suffix(".pt")
    parameters = {"learning_rate": optimizer.param_groups[0]["lr"],
                  "momentum": optimizer.param_groups[0]["momentum"],
                  "weight_decay": optimizer.param_groups[0]["weight_decay"],
                  "target_steps": target_steps}
    progress = session.new_progress(
        range(next_step, target_steps), description="RTX 5060 training demo",
        total=target_steps, initial=next_step,
        parameters=parameters, csv_path=csv_path, console_path=console_path,
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
            print(f"Run ID: {session.run_id}; initial step: {next_step}; target: {target_steps}")
            print(f"Hyperparameters: {parameters}")
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
                if step_delay:
                    sleep(step_delay)

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
        progress.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--steps", type=int, help="Total target steps, including steps before resume")
    parser.add_argument("--step-delay", type=float, default=0.03)
    parser.add_argument("--resume", type=Path, help="Resume from a saved .pt training checkpoint")
    parser.add_argument("--learning-rate", type=float, default=0.1)
    parser.add_argument("--momentum", type=float, default=0.0)
    parser.add_argument("--weight-decay", type=float, default=0.0)
    args = parser.parse_args()
    if (args.steps is not None and args.steps <= 0) or not 0 <= args.step_delay < float("inf"):
        parser.error("steps must be positive and step-delay must be finite and non-negative")

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable. This demo requires the NVIDIA GPU.")

    parameters = validate_parameters({"learning_rate": args.learning_rate,
                                      "momentum": args.momentum,
                                      "weight_decay": args.weight_decay,
                                      "target_steps": args.steps or 1000})
    session = TrainingSession(parameters, validate_parameters)
    session.run(lambda current, config: train_run(current, config, args.resume,
                                                  args.steps is not None, args.step_delay),
                open_browser=not args.no_browser, keep_open=args.keep_open)


if __name__ == "__main__":
    main()
