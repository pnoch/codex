from __future__ import annotations

import importlib.resources as resources
import inspect
from typing import Any

from codex_app_server import AppServerConfig
from codex_app_server.public_api import AsyncCodex, AsyncThread, Codex, Thread


def _keyword_only_names(fn: object) -> list[str]:
    signature = inspect.signature(fn)
    return [
        param.name
        for param in signature.parameters.values()
        if param.kind == inspect.Parameter.KEYWORD_ONLY
    ]


def _assert_no_any_annotations(fn: object) -> None:
    signature = inspect.signature(fn)
    for param in signature.parameters.values():
        if param.annotation is Any:
            raise AssertionError(f"{fn} has public parameter typed as Any: {param.name}")
    if signature.return_annotation is Any:
        raise AssertionError(f"{fn} has public return annotation typed as Any")


def test_root_exports_app_server_config() -> None:
    assert AppServerConfig.__name__ == "AppServerConfig"


def test_package_includes_py_typed_marker() -> None:
    marker = resources.files("codex_app_server").joinpath("py.typed")
    assert marker.is_file()


def test_generated_public_signatures_are_snake_case_and_typed() -> None:
    expected = {
        Codex.thread_start: [
            "approval_policy",
            "base_instructions",
            "config",
            "cwd",
            "developer_instructions",
            "ephemeral",
            "model",
            "model_provider",
            "personality",
            "sandbox",
        ],
        Codex.thread_list: [
            "archived",
            "cursor",
            "cwd",
            "limit",
            "model_providers",
            "sort_key",
            "source_kinds",
        ],
        Thread.turn: [
            "approval_policy",
            "cwd",
            "effort",
            "model",
            "output_schema",
            "personality",
            "sandbox_policy",
            "summary",
        ],
        Thread.resume: [
            "approval_policy",
            "base_instructions",
            "config",
            "cwd",
            "developer_instructions",
            "model",
            "model_provider",
            "personality",
            "sandbox",
        ],
        Thread.fork: [
            "approval_policy",
            "base_instructions",
            "config",
            "cwd",
            "developer_instructions",
            "model",
            "model_provider",
            "sandbox",
        ],
        AsyncCodex.thread_start: [
            "approval_policy",
            "base_instructions",
            "config",
            "cwd",
            "developer_instructions",
            "ephemeral",
            "model",
            "model_provider",
            "personality",
            "sandbox",
        ],
        AsyncCodex.thread_list: [
            "archived",
            "cursor",
            "cwd",
            "limit",
            "model_providers",
            "sort_key",
            "source_kinds",
        ],
        AsyncThread.turn: [
            "approval_policy",
            "cwd",
            "effort",
            "model",
            "output_schema",
            "personality",
            "sandbox_policy",
            "summary",
        ],
        AsyncThread.resume: [
            "approval_policy",
            "base_instructions",
            "config",
            "cwd",
            "developer_instructions",
            "model",
            "model_provider",
            "personality",
            "sandbox",
        ],
        AsyncThread.fork: [
            "approval_policy",
            "base_instructions",
            "config",
            "cwd",
            "developer_instructions",
            "model",
            "model_provider",
            "sandbox",
        ],
    }

    for fn, expected_kwargs in expected.items():
        actual = _keyword_only_names(fn)
        assert actual == expected_kwargs, f"unexpected kwargs for {fn}: {actual}"
        assert all(name == name.lower() for name in actual), f"non snake_case kwargs in {fn}: {actual}"
        _assert_no_any_annotations(fn)
