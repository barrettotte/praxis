from collections.abc import Callable
from typing import Any, ClassVar

__version__: str

class Signature:
    instructions: ClassVar[str]
    @classmethod
    def with_instructions(cls, instructions: str) -> type[Signature]: ...

def InputField(**kwargs: Any) -> Any: ...
def OutputField(**kwargs: Any) -> Any: ...

class Example:
    def __init__(self, base: object | None = None, **kwargs: Any) -> None: ...
    def with_inputs(self, *keys: str) -> Example: ...

class Predict:
    signature: Signature
    def __init__(self, signature: type[Signature]) -> None: ...
    def __call__(self, **kwargs: Any) -> Any: ...

class LM:
    def __init__(
        self,
        model: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        cache: bool = True,
        **kwargs: Any,
    ) -> None: ...

class JSONAdapter: ...

class MIPROv2:
    def __init__(
        self,
        metric: Callable[..., float],
        *,
        prompt_model: object | None = None,
        task_model: object | None = None,
        auto: str | None = "light",
        num_candidates: int | None = None,
        num_threads: int | None = None,
        max_errors: int | None = None,
        seed: int = 9,
        init_temperature: float = 1.0,
        verbose: bool = False,
    ) -> None: ...
    def compile(
        self,
        student: object,
        *,
        trainset: list[object],
        valset: list[object] | None = None,
        num_trials: int | None = None,
        max_bootstrapped_demos: int | None = None,
        max_labeled_demos: int | None = None,
        minibatch: bool = True,
        program_aware_proposer: bool = True,
        data_aware_proposer: bool = True,
        tip_aware_proposer: bool = True,
        fewshot_aware_proposer: bool = True,
    ) -> object: ...

def configure_cache(
    *,
    enable_disk_cache: bool = True,
    enable_memory_cache: bool = True,
) -> None: ...
def configure(**kwargs: Any) -> None: ...
