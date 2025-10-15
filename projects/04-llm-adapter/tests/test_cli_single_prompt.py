from __future__ import annotations

import adapter.cli.prompts as _prompts_module
from adapter.cli.runner import classify_error as _classify_error  # noqa: F401
from adapter.cli.utils import _msg as _msg  # noqa: F401

from .cli_single_prompt.conftest import *  # noqa: F401,F403
from .cli_single_prompt.test_credentials import *  # noqa: F401,F403
from .cli_single_prompt.test_openrouter_flow import *  # noqa: F401,F403
from .cli_single_prompt.test_prompt_flow import *  # noqa: F401,F403
from .cli_single_prompt.test_provider_errors import *  # noqa: F401,F403

if not hasattr(_prompts_module, "_classify_error"):
    _prompts_module._classify_error = _classify_error
if not hasattr(_prompts_module, "_msg"):
    _prompts_module._msg = _msg
