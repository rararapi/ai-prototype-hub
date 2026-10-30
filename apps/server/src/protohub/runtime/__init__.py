from protohub.domain.ports import RuntimeProvider
from protohub.domain.settings import Settings


def make_runtime(settings: Settings) -> RuntimeProvider:
    if settings.runtime_mode == "mock":
        from protohub.runtime.mock import MockRuntime

        return MockRuntime()
    from protohub.runtime.kubernetes import KubernetesRuntime

    return KubernetesRuntime.in_cluster(settings)
