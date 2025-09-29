from collections.abc import Mapping, Sequence
from typing import Any, IO

class Loader: ...

class Dumper: ...

class YAMLError(Exception):
    ...

def safe_load(stream: str | bytes | IO[str] | IO[bytes]) -> Any: ...

def safe_dump(
    data: Any,
    stream: IO[str] | IO[bytes] | None = ...,
    *,
    default_flow_style: bool | None = ...,
    encoding: str | None = ...,
) -> str | bytes | None: ...

def load(
    stream: str | bytes | IO[str] | IO[bytes],
    Loader: type[Loader] | None = ...,
) -> Any: ...

def dump(
    data: Any,
    stream: IO[str] | IO[bytes] | None = ...,
    Dumper: type[Dumper] | None = ...,
    *,
    default_flow_style: bool | None = ...,
    encoding: str | None = ...,
) -> str | bytes | None: ...

def safe_load_all(
    stream: str | bytes | IO[str] | IO[bytes]
) -> Sequence[Mapping[str, Any]]: ...
