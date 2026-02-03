from __future__ import annotations

def hf_hub_download(
    repo_id: str,
    filename: str,
    **kwargs: object,
) -> str: ...
def snapshot_download(
    repo_id: str,
    **kwargs: object,
) -> str: ...
