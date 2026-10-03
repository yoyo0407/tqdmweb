"""Executed in the selected Python environment; never imports the training script."""

import json
import math
import sys


def option(argv, name, default=None):
    values = [value.split('=', 1)[1] if value.startswith(name + '=') else argv[index + 1]
              for index, value in enumerate(argv) if value == name or value.startswith(name + '=')]
    return int(values[-1]) if values else default


def inspect(payload):
    import torch
    contract, argv = payload['contract'], payload['argv']
    state = torch.load(payload['path'], map_location='cpu', weights_only=True)
    if not isinstance(state, dict):
        raise ValueError('Checkpoint must contain a training state dictionary')
    kind = contract['checkpoint_format']
    if kind == 'qtqdm-2048-v1':
        if state.get('format') != kind:
            raise ValueError('Checkpoint format does not match this 2048 script')
        required = {'agent', 'optimizer', 'training', 'replay_capacity', 'replay_count', 'replay',
                    'board', 'env_rng', 'numpy_rng', 'torch_rng', 'cuda_rng'}
        missing = required - state.keys()
        if missing:
            raise ValueError('Incomplete checkpoint; missing: ' + ', '.join(sorted(missing)))
        step = state['training']['next_step']
        target = option(argv, '--steps', contract.get('default_steps', 20000))
        capacity = option(argv, '--buffer-size', contract.get('default_buffer_size', 20000))
        if type(state['replay_capacity']) is not int or state['replay_capacity'] != capacity:
            raise ValueError(f'Replay buffer mismatch; use --buffer-size {state["replay_capacity"]}')
        count = state['replay_count']
        if type(count) is not int or count < 0 or capacity <= 0:
            raise ValueError('Invalid replay buffer metadata')
        for name in ('state_memory', 'new_state_memory', 'action_memory', 'reward_memory', 'terminal_memory'):
            value = state['replay'].get(name)
            if not isinstance(value, torch.Tensor) or len(value) != min(count, capacity):
                raise ValueError(f'Incomplete replay buffer: {name}')
        if not isinstance(state['board'], torch.Tensor) or tuple(state['board'].shape) != (4, 4):
            raise ValueError('Invalid 2048 board shape')
        model = state['agent']
    else:
        if state.get('format_version') != 1:
            raise ValueError('Unsupported training checkpoint version')
        required = {'model', 'optimizer', 'next_step', 'target_steps', 'cpu_rng_state', 'cuda_rng_state'}
        missing = required - state.keys()
        if missing:
            raise ValueError('Incomplete checkpoint; missing: ' + ', '.join(sorted(missing)))
        step = state['next_step']
        target = option(argv, '--steps', state['target_steps'])
        model = state['model']
    if type(step) is not int or step < 0 or type(target) is not int or target <= step:
        raise ValueError(f'Resume requires --steps greater than saved step {step}')
    if not isinstance(model, dict) or not model:
        raise ValueError('Missing model weights')
    if contract.get('strict_model') and set(model) != set(contract.get('model_shapes', {})):
        raise ValueError('Model state keys do not match this script')
    for name, shape in contract.get('model_shapes', {}).items():
        value = model.get(name)
        if not isinstance(value, torch.Tensor) or list(value.shape) != shape:
            raise ValueError(f'Model shape mismatch: {name}; expected {shape}')
    groups = state['optimizer'].get('param_groups', [])
    if not groups or not isinstance(state['optimizer'].get('state'), dict):
        raise ValueError('Incomplete optimizer state')
    rate = groups[0].get('lr')
    if not isinstance(rate, (int, float)) or not math.isfinite(rate) or rate <= 0:
        raise ValueError('Invalid saved learning rate')
    return {'valid': True, 'format': kind, 'next_step': step, 'target_steps': target, 'learning_rate': rate}


if __name__ == '__main__':
    try:
        result = inspect(json.load(sys.stdin))
    except Exception as error:
        result = {'valid': False, 'error': f'{type(error).__name__}: {error}'}
    print(json.dumps(result))
