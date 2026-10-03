from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

try:
    import torch
except ModuleNotFoundError:
    torch = None


@unittest.skipIf(torch is None, "Checkpoint tests require the GPU environment's PyTorch")
class CheckpointTests(unittest.TestCase):
    def setUp(self):
        from training_checkpoint import load_checkpoint, save_checkpoint
        self.load_checkpoint = load_checkpoint
        self.save_checkpoint = save_checkpoint
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "training.pt"

    def train(self, model, optimizer, count):
        for _ in range(count):
            inputs = torch.randn(16, 3)
            targets = inputs.sum(dim=1, keepdim=True)
            loss = ((model(inputs) - targets) ** 2).mean()
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

    def test_resume_matches_uninterrupted_training(self):
        torch.manual_seed(314)
        model = torch.nn.Linear(3, 1)
        optimizer = torch.optim.SGD(model.parameters(), lr=0.025, momentum=0.9)
        self.train(model, optimizer, 4)
        self.save_checkpoint(self.path, model, optimizer, 4, 8)
        self.train(model, optimizer, 4)
        expected = {key: value.clone() for key, value in model.state_dict().items()}

        resumed_model = torch.nn.Linear(3, 1)
        resumed_optimizer = torch.optim.SGD(resumed_model.parameters(), lr=1.0)
        metadata = self.load_checkpoint(self.path, resumed_model, resumed_optimizer)
        self.assertEqual(metadata, {"next_step": 4, "target_steps": 8})
        self.assertEqual(resumed_optimizer.param_groups[0]["lr"], 0.025)
        self.assertEqual(resumed_optimizer.param_groups[0]["momentum"], 0.9)
        self.assertTrue(resumed_optimizer.state)
        self.train(resumed_model, resumed_optimizer, 4)
        for key, value in resumed_model.state_dict().items():
            self.assertTrue(torch.equal(value, expected[key]), key)

    def test_failed_save_keeps_previous_file(self):
        self.path.write_bytes(b"previous checkpoint")
        model = torch.nn.Linear(3, 1)
        optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
        with patch("training_checkpoint.torch.save", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                self.save_checkpoint(self.path, model, optimizer, 0, 8)
        self.assertEqual(self.path.read_bytes(), b"previous checkpoint")
        self.assertFalse(self.path.with_suffix(".pt.tmp").exists())

    def test_invalid_checkpoint_format(self):
        torch.save({"format_version": 99}, self.path)
        model = torch.nn.Linear(3, 1)
        optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            self.load_checkpoint(self.path, model, optimizer)


if __name__ == "__main__":
    unittest.main()
