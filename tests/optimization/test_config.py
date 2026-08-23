import math

import pytest

from kubernetes_resource_optimizer.data.models import Resource
from kubernetes_resource_optimizer.optimization.config import OptimizationConfig


def test_resource_specific_configuration_accessors() -> None:
    config = OptimizationConfig(0.05, 0.1, 0.01, 0.02, 1.5, 1.25)

    assert config.epsilon_request(Resource.CPU) == 0.05
    assert config.epsilon_request(Resource.MEMORY) == 0.1
    assert config.epsilon_limit(Resource.CPU) == 0.01
    assert config.epsilon_limit(Resource.MEMORY) == 0.02
    assert config.limit_overcommit(Resource.CPU) == 1.5
    assert config.limit_overcommit(Resource.MEMORY) == 1.25
    assert config.maximum_request_violations(Resource.CPU, 20) == 1
    assert config.maximum_request_violations(Resource.MEMORY, 20) == 2
    assert config.maximum_limit_violations(Resource.CPU, 100) == 1
    assert config.maximum_limit_violations(Resource.MEMORY, 100) == 2


@pytest.mark.parametrize("epsilon", [-0.01, 1.01, math.inf, math.nan])
def test_rejects_invalid_epsilon(epsilon: float) -> None:
    with pytest.raises(ValueError, match="epsilon_cpu_request"):
        OptimizationConfig(epsilon, 0, 0, 0, 1, 1)


@pytest.mark.parametrize("factor", [-0.01, math.inf, math.nan])
def test_rejects_invalid_overcommit_factor(factor: float) -> None:
    with pytest.raises(ValueError, match="cpu_limit_overcommit"):
        OptimizationConfig(0, 0, 0, 0, factor, 1)
