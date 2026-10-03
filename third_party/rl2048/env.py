"""Headless 2048 environment adapted from HAN-oQo and activatedgeek.

MIT notices: License and GYM_LICENSE. Local changes: UPSTREAM.md.
"""

import numpy as np

import gymnasium as gym
import gymnasium.spaces as spaces

class Base2048Env(gym.Env):
    metadata = {
        'render_modes': ['human'],
        'render_fps': 4
    }

    ##
    # NOTE: Don't modify these numbers as
    # they define the number of
    # anti-clockwise rotations before
    # applying the left action on a grid
    #
    LEFT = 0
    UP = 1
    RIGHT = 2
    DOWN = 3

    ACTION_STRING = {
        LEFT: 'left',
        UP: 'up',
        RIGHT: 'right',
        DOWN: 'down',
    }

    def __init__(self, render_mode=None, width=4, height=4):
        self.width = width
        self.height = height

        self.observation_space = spaces.Box(
            low=0, high=2**32, shape=(self.width * self.height,), dtype=np.int64)
        self.action_space = spaces.Discrete(4)

        # Internal Variables
        self.board = None
        self.np_random = None
        assert render_mode is None or render_mode in self.metadata["render_modes"]
        self.render_mode = render_mode

    def _get_obs(self):
        return self.board.flatten()

    def reset(self, seed=None, options=None):
        """Place 2 tiles on empty board."""
        super().reset(seed=seed)
        self.board = np.zeros((self.width, self.height), dtype=np.int64)
        self._place_random_tiles(self.board, count=2)
        obs = self._get_obs()

        return obs, {"action_mask": self.is_done()[1]}

    def step(self, action: int):
        """Rotate board aligned with left action"""

        # Align board action with left action
        prev_board = self.board.copy()

        rotated_obs = np.rot90(self.board, k=action)
        reward, updated_obs = self._slide_left_and_merge(rotated_obs)
        self.board = np.rot90(updated_obs, k=4 - action)

        # Place one random tile on empty location
        if not np.array_equal(prev_board, self.board):
            self._place_random_tiles(self.board, count=1)

        done, action_mask = self.is_done()
        obs = self._get_obs()

        return obs, reward, done, False, {"action_mask": action_mask}

    def is_done(self):
        action_mask = []
        for action in range(4):
            rotated = np.rot90(self.board, k=action)
            _, moved = self._slide_left_and_merge(rotated)
            action_mask.append(int(not np.array_equal(rotated, moved)))
        return not any(action_mask), action_mask

    def render(self):

        if self.render_mode == 'human':
            for row in self.board.tolist():
                print(' \t'.join(map(str, row)))
            print("=============================")
        else:
            raise ValueError("This demo supports only headless or text rendering")

    def _sample_tiles(self, count=1):
        """Sample tile 2 or 4."""

        choices = [2, 4]
        probs = [0.9, 0.1]

        tiles = self.np_random.choice(choices, size=count, p=probs)
        return tiles.tolist()

    def _sample_tile_locations(self, board, count=1):
        """Sample grid locations with no tile."""

        zero_locs = np.argwhere(board == 0)
        zero_indices = self.np_random.choice(len(zero_locs), size=count, replace=False)

        zero_pos = zero_locs[zero_indices]
        zero_pos = zero_pos.tolist()
        return zero_pos

    def _place_random_tiles(self, board, count=1):
        if not board.all():
            tiles = self._sample_tiles(count)
            tile_locs = self._sample_tile_locations(board, count)
            for tile,tile_loc in zip(tiles, tile_locs):

                board[tile_loc[0], tile_loc[1]] = tile

    def _slide_left_and_merge(self, board):
        """Slide tiles on a grid to the left and merge."""

        result = []

        score = 0
        for row in board:
            row = np.extract(row > 0, row)
            score_, result_row = self._try_merge(row)
            score += score_
            row = np.pad(np.array(result_row), (0, self.width - len(result_row)),
                         'constant', constant_values=(0,))
            result.append(row)

        return score, np.array(result, dtype=np.int64)

    @staticmethod
    def _try_merge(row):
        score = 0
        result_row = []

        i = 1
        while i < len(row):
            if row[i] == row[i - 1]:
                score += row[i] + row[i - 1]
                result_row.append(row[i] + row[i - 1])
                i += 2
            else:
                result_row.append(row[i - 1])
                i += 1

        if i == len(row):
            result_row.append(row[i - 1])

        return score, result_row
