import unittest
from training_config import DEFAULT_PARAMETERS, validate_parameters


class TrainingConfigTests(unittest.TestCase):
    def test_hyperparameter_validation(self):
        for override in ({"learning_rate": 0}, {"learning_rate": True}, {"learning_rate": float("inf")},
                         {"momentum": 1}, {"momentum": -1}, {"weight_decay": -1},
                         {"target_steps": 0}, {"target_steps": 1.5}, {"unknown": 1}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                validate_parameters({**DEFAULT_PARAMETERS, **override})
        self.assertEqual(validate_parameters(DEFAULT_PARAMETERS), DEFAULT_PARAMETERS)
