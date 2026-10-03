from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

try:
    import gymnasium
    import numpy as np
    import torch
except ModuleNotFoundError:
    torch = None


@unittest.skipIf(torch is None, "2048 tests require PyTorch and requirements-2048.txt")
class RL2048Tests(unittest.TestCase):
    def setUp(self):
        from third_party.rl2048.env import Base2048Env
        from third_party.rl2048.dqn import DQN, ReplayBuffer
        from rl2048_demo import encode
        self.Env, self.DQN, self.Buffer, self.encode = Base2048Env, DQN, ReplayBuffer, encode

    def agent(self, device="cpu"):
        config = {"architecture": "linear", "hidden_layer": 2, "hidden_units": 16,
                  "non_linearity": "ReLU", "learning_rate": {"policy": 0.001},
                  "discount": 0.99, "target_smoothing_coefficient": 0.05}
        return self.DQN(16, 4, config).to(device)

    def test_game_merges_once_and_spawns_only_on_legal_moves(self):
        env = self.Env()
        for seed in range(20):
            env.reset(seed=seed)
            self.assertEqual(np.count_nonzero(env.board), 2)
        env.board = np.zeros((4, 4), dtype=np.int64)
        env.board[0] = [2, 2, 2, 2]
        score, moved = env._slide_left_and_merge(env.board)
        self.assertEqual(score, 8)
        np.testing.assert_array_equal(moved[0], [4, 4, 0, 0])
        self.assertEqual(moved.sum(), env.board.sum())
        env.board = np.zeros((4, 4), dtype=np.int64)
        env.board[0, 0] = 2
        before = env.board.copy()
        rng_before = repr(env.np_random.bit_generator.state)
        _, reward, done, _, info = env.step(env.LEFT)
        np.testing.assert_array_equal(env.board, before)
        self.assertEqual(reward, 0)
        self.assertFalse(done)
        self.assertEqual(rng_before, repr(env.np_random.bit_generator.state))
        self.assertEqual(info["action_mask"], [0, 0, 1, 1])
        env.step(env.RIGHT)
        self.assertIn(int(env.board.sum()), (4, 6))
        self.assertEqual(np.count_nonzero(env.board), 2)

    def test_terminal_board_and_valid_action_with_negative_q_values(self):
        env = self.Env()
        env.reset(seed=42)
        env.board = np.array([[2, 4, 2, 4], [4, 2, 4, 2]] * 2, dtype=np.int64)
        self.assertEqual(env.is_done(), (True, [0, 0, 0, 0]))
        agent = self.agent()
        with torch.no_grad():
            for parameter in agent.q_action.parameters():
                parameter.zero_()
            agent.q_action.fc[-1].bias.copy_(torch.tensor([-1., -2., -3., -4.]))
        observation = torch.zeros(1, 16)
        mask = torch.tensor([False, False, True, False])
        for epsilon in (0, 1):
            for _ in range(10):
                self.assertEqual(agent.get_action(observation, epsilon, mask), 2)

    def test_optimizer_updates_policy_without_target_gradients(self):
        agent = self.agent()
        before = [parameter.detach().clone() for parameter in agent.q_action.parameters()]
        batch = (torch.randn(8, 16), torch.zeros(8, 1, dtype=torch.long), torch.ones(8, 1),
                 torch.randn(8, 16), torch.ones(8, 1))
        loss = agent.train_net(batch)
        self.assertTrue(np.isfinite(loss))
        self.assertTrue(any(not torch.equal(old, new) for old, new in zip(before, agent.q_action.parameters())))
        self.assertTrue(all(parameter.grad is None for parameter in agent.q_eval.parameters()))

    def test_checkpoint_resume_preserves_game_replay_rng_and_model(self):
        import rl2048_checkpoint as checkpoint
        devices = ["cpu"] + (["cuda:0"] if torch.cuda.is_available() else [])
        for device in devices:
            with self.subTest(device=device), TemporaryDirectory() as folder:
                torch.manual_seed(42)
                np.random.seed(42)
                env = self.Env()
                env.reset(seed=42)
                agent, memory = self.agent(device), self.Buffer(8, 16, 1)
                def moves(env, agent, memory, count):
                    for _ in range(count):
                        obs = self.encode(env.board)
                        mask = torch.tensor(env.is_done()[1], dtype=torch.bool, device=device)
                        action = agent.get_action(torch.as_tensor(obs, device=device).unsqueeze(0), 0.5, mask)
                        _, reward, done, _, _ = env.step(action)
                        memory.put(obs, action, reward / 100, self.encode(env.board), done)
                        if memory.size() >= 4:
                            agent.train_net(self.Buffer.batch_to_device(memory.sample(4), device))
                        if done:
                            env.reset()
                moves(env, agent, memory, 12)  # Wrap the ring buffer before saving.
                path = Path(folder) / "2048.pt"
                checkpoint.save(path, agent, memory, env, {"next_step": 12})
                moves(env, agent, memory, 15)
                expected_model = {key: value.detach().clone() for key, value in agent.state_dict().items()}
                expected_board = env.board.copy()
                resumed_env = self.Env()
                resumed_env.reset(seed=999)
                resumed_agent, resumed_memory = self.agent(device), self.Buffer(8, 16, 1)
                self.assertEqual(checkpoint.load(path, resumed_agent, resumed_memory, resumed_env), {"next_step": 12})
                self.assertEqual(resumed_memory.mem_cntr, 12)
                moves(resumed_env, resumed_agent, resumed_memory, 15)
                np.testing.assert_array_equal(resumed_env.board, expected_board)
                for key, value in resumed_agent.state_dict().items():
                    self.assertTrue(torch.equal(value, expected_model[key]), key)
                self.assertEqual(resumed_memory.mem_cntr, memory.mem_cntr)
                np.testing.assert_array_equal(resumed_memory.state_memory, memory.state_memory)


if __name__ == "__main__":
    unittest.main()
