from datetime import timedelta

from strands.tools.mcp import MCPTransport

def aws_iam_streamablehttp_client(
    endpoint: str,
    aws_service: str,
    aws_region: str | None = ...,
    aws_profile: str | None = ...,
    *,
    timeout: float | timedelta = ...,
    sse_read_timeout: float | timedelta = ...,
) -> MCPTransport: ...
