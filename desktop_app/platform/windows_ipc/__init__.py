from __future__ import annotations

from desktop_app.platform.windows_ipc.named_pipe import (
    TRANSLATOR_WINDOWS_PIPE_NAME_ENV as TRANSLATOR_WINDOWS_PIPE_NAME_ENV,
)
from desktop_app.platform.windows_ipc.named_pipe import pipe_name as pipe_name
from desktop_app.platform.windows_ipc.protocol import PipeCommand as PipeCommand
from desktop_app.platform.windows_ipc.protocol import PipeCommandName as PipeCommandName
from desktop_app.platform.windows_ipc.protocol import PipeResponse as PipeResponse
from desktop_app.platform.windows_ipc.protocol import (
    PipeResponseStatus as PipeResponseStatus,
)
from desktop_app.platform.windows_ipc.protocol import decode_command as decode_command
from desktop_app.platform.windows_ipc.protocol import decode_response as decode_response
from desktop_app.platform.windows_ipc.protocol import encode_command as encode_command
from desktop_app.platform.windows_ipc.protocol import encode_response as encode_response
from desktop_app.platform.windows_ipc.service import PipeHandlers as PipeHandlers
from desktop_app.platform.windows_ipc.service import (
    WindowsIpcService as WindowsIpcService,
)
from desktop_app.platform.windows_ipc.service import dispatch_command as dispatch_command

__all__ = [
    "PipeCommand",
    "PipeCommandName",
    "PipeResponse",
    "PipeResponseStatus",
    "PipeHandlers",
    "WindowsIpcService",
    "TRANSLATOR_WINDOWS_PIPE_NAME_ENV",
    "pipe_name",
    "encode_command",
    "decode_command",
    "encode_response",
    "decode_response",
    "dispatch_command",
]
