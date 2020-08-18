import numpy as np
import ray
from ray.rllib.agents.ppo import PPOTrainer

from rld.attributation import AttributationTarget
from rld.config import Config
from rld.model import Model, RayModelWrapper
from rld.typing import ObsLike


def get_model() -> Model:
    ray.init()
    trainer = PPOTrainer(config={"env": "CartPole-v1", "framework": "torch",})
    model = RayModelWrapper(trainer.get_policy().model)
    ray.shutdown()
    return model


def baseline_builder(obs: ObsLike):
    return np.zeros_like(obs)


model = get_model()


config = Config(model=model, baseline=baseline_builder, target=AttributationTarget.ALL,)
