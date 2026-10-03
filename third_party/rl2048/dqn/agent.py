# Adapted from HAN-oQo/RL_for_2048; MIT notice in ../License.
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import numpy as np
from .networks import PolicyNet, PolicyNet_FC

"""
Separated Policy network and Target network
"""
class DQN(nn.Module):
    def __init__(self, obs_dim, action_dim, config):
        super(DQN, self).__init__()
        self.action_dim = action_dim
        if config["architecture"] == "conv":
            self.q_action = PolicyNet(obs_dim, action_dim, config)
            self.q_eval = PolicyNet(obs_dim, action_dim, config)
        else:
            self.q_action = PolicyNet_FC(obs_dim, action_dim, config)
            self.q_eval = PolicyNet_FC(obs_dim, action_dim, config)
        self.q_eval.load_state_dict(self.q_action.state_dict())

        self.optimizer = optim.Adam(self.q_action.parameters(), lr=config["learning_rate"]["policy"])
        self.tau = config["target_smoothing_coefficient"]
        self.gamma =config["discount"]

    def forward(self, s, a, s_prime):
        a = a.to(device=s.device, dtype=torch.long)
        q_pred = self.q_action(s).gather(dim=-1, index=a)
        with torch.no_grad():
            q_next = self.q_eval(s_prime).max(dim=-1, keepdim=True)[0]
        return q_pred, q_next

    def train_net(self,mini_batch):
        s, a, r, s_prime, done = mini_batch

        self.optimizer.zero_grad()
        q_pred, q_next = self.forward(s,a,s_prime)

        q_target = r + done *self.gamma * q_next
        loss = F.mse_loss(q_pred, q_target).mean()
        loss.backward()
        self.optimizer.step()
        self.soft_update()

        return loss.item()

    def get_action(self, s, eps, action_mask):
        with torch.no_grad():
            if np.random.random() > eps:
                q_pred = self.q_action(s)
                q_pred = q_pred.masked_fill(~action_mask.bool(), -torch.inf)
                a = torch.argmax(q_pred, dim=-1)
                a = a.detach().cpu().numpy()
            else:
                valid = torch.nonzero(action_mask, as_tuple=False).flatten().cpu().numpy()
                a = np.random.choice(valid)

        return int(np.asarray(a).item())

    def soft_update(self):
        for param_target, param in zip(self.q_eval.parameters(), self.q_action.parameters()):
            param_target.data.copy_(param_target.data * (1.0 - self.tau) + param.data * self.tau)


    def save_ckpt(self, ckpt_path):
        torch.save({"q_action": self.q_action.state_dict(),
                    "q_eval": self.q_eval.state_dict(),
                    "optim": self.optimizer.state_dict(),
                    }, ckpt_path)

    def load_ckpt(self, ckpt_path):
        checkpoint = torch.load(ckpt_path, map_location="cpu", weights_only=True)
        self.q_action.load_state_dict(checkpoint["q_action"])
        self.q_eval.load_state_dict(checkpoint["q_eval"])
        self.optimizer.load_state_dict(checkpoint["optim"])
        print("Model: {} Loaded!".format(ckpt_path))
