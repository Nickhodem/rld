from abc import ABC
from collections import OrderedDict
from typing import Any, List

import numpy as np
import torch
import torch.nn as nn
import tree
from gym import Space
from gym.spaces import flatten, unflatten, Box, Dict
from ray.rllib.models.modelv2 import ModelV2
from ray.rllib.models.preprocessors import get_preprocessor

from rld.exception import SpaceNotSupported
from rld.typing import (
    ObsLike,
    ObsLikeStrict,
    ObsTensorLike,
    ObsTensorStrict,
    HiddenState,
)


class Model(ABC, nn.Module):
    def input_device(self) -> torch.device:
        raise NotImplementedError

    def output_device(self) -> torch.device:
        return self.input_device()

    def action_space(self) -> Space:
        raise NotImplementedError

    def obs_space(self) -> Space:
        raise NotImplementedError

    def flatten_obs(self, obs: ObsLike) -> ObsLikeStrict:
        if isinstance(self.obs_space(), Box):
            return obs
        return flatten(self.obs_space(), obs)

    def unflatten_obs(self, obs: ObsLikeStrict) -> ObsLike:
        if isinstance(self.obs_space(), Box):
            return obs
        return unflatten(self.obs_space(), obs)

    # From PyTorch 1.6
    def _forward_unimplemented(self, *input: Any) -> None:
        pass


class RecurrentModel(Model, ABC):
    def initial_state(self) -> HiddenState:
        raise NotImplementedError


RayModel = ModelV2


class RayModelWrapper(Model):
    def __init__(self, model: RayModel):
        super().__init__()
        self.model = model
        self.preprocessor = get_preprocessor(self.obs_space())(self.obs_space())

    def unwrapped(self):
        return self.model

    def forward(self, x):
        if isinstance(self.obs_space(), Box):
            input_dict = {"obs": unpack_tensor(x, self.obs_space()), "obs_flat": x}
        else:
            input_dict = {"obs": x, "obs_flat": x}
        state = None
        seq_lens = None
        return self.model(input_dict, state, seq_lens)[0]

    def input_device(self) -> torch.device:
        return next(self.model.parameters()).device

    def action_space(self) -> Space:
        return self.model.action_space

    def obs_space(self) -> Space:
        if hasattr(self.model.obs_space, "original_space"):
            return self.model.obs_space.original_space
        else:
            return self.model.obs_space


def pack_array(obs: ObsLike, space: Space) -> ObsLikeStrict:
    if isinstance(space, Box):
        return np.asarray(obs, dtype=np.float32).flatten()
    elif isinstance(space, Dict):
        packed_values = [pack_array(obs[name], s) for name, s in space.spaces.items()]
        return np.concatenate(packed_values)
    else:
        raise SpaceNotSupported(space)


def unpack_array(obs: ObsLikeStrict, space: Space) -> ObsLike:
    if isinstance(space, Box):
        return np.asarray(obs).reshape(space.shape)
    elif isinstance(space, Dict):
        sizes = [_packed_size(s) for s in space.spaces.values()]
        split_packed = np.split(obs, np.cumsum(sizes)[:-1])
        split_unpacked = [
            (name, unpack_array(unpacked, s))
            for unpacked, (name, s) in zip(split_packed, space.spaces.items())
        ]
        return OrderedDict(split_unpacked)
    else:
        raise SpaceNotSupported(space)


def unpack_tensor(obs: ObsTensorStrict, space: Space) -> ObsTensorLike:
    batch_size = obs.size(0) if obs.ndim > 1 else None
    if batch_size is None:
        return _unpack_tensor_single(obs, space)
    else:
        return _unpack_tensor_batched(obs, space)


def _unpack_tensor_single(obs: ObsTensorStrict, space: Space) -> ObsTensorLike:
    if isinstance(space, Box):
        return obs.reshape(space.shape)
    elif isinstance(space, Dict):
        sizes = [_packed_size(s) for s in space.spaces.values()]
        split_packed = torch.split(obs, sizes)
        split_unpacked = [
            (name, unpack_tensor(unpacked, s))
            for unpacked, (name, s) in zip(split_packed, space.spaces.items())
        ]
        return OrderedDict(split_unpacked)
    else:
        raise SpaceNotSupported(space)


def _unpack_tensor_batched(obs: ObsTensorStrict, space: Space) -> ObsTensorLike:
    batch_size = obs.size(0)
    return _merge_unpacked_batch(
        [unpack_tensor(obs[b], space) for b in range(batch_size)]
    )


def _merge_unpacked_batch(obs_list: List[ObsTensorLike]) -> ObsTensorLike:
    return tree.map_structure(lambda *elems: torch.stack(elems, dim=0), *obs_list)


def _packed_size(space: Space) -> int:
    if isinstance(space, Box):
        return int(np.prod(space.shape))
    elif isinstance(space, Dict):
        return int(sum([_packed_size(s) for s in space.spaces]))
    else:
        raise SpaceNotSupported(space)
