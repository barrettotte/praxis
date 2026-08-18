"""Construct the local Strands agent."""

from boto3.session import Session
from strands import Agent
from strands.models import BedrockModel

from praxis.config import AgentSettings, load_settings

SYSTEM_PROMPT = """You are Praxis, a project-planning assistant.
Help the user clarify a software project goal and keep recommendations concise.
Do not claim to have searched personal evidence until catalog tools are available.
"""


def create_agent(settings: AgentSettings) -> Agent:
    """Create a Strands agent configured for Amazon Bedrock."""
    boto_session = Session(region_name=settings.region)
    model = BedrockModel(
        boto_session=boto_session,
        model_id=settings.model_id,
        temperature=0.1,
    )
    return Agent(model=model, system_prompt=SYSTEM_PROMPT, callback_handler=None)


def invoke(prompt: str, settings: AgentSettings | None = None) -> str:
    """Invoke the local agent and return its text representation."""
    configured_settings = settings or load_settings()
    result = create_agent(configured_settings)(prompt)
    return str(result)
