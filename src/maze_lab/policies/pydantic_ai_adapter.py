"""PydanticAI LLM policy: exactly one provider request per decision (spec §6.2, §13).

Strict condition, enforced here:
- a fresh `Agent` run per decision with no message history;
- framework retries and output repair disabled (`retries=0`);
- provider SDK clients built with `max_retries=0`;
- the raw model output is re-parsed by the strict contract parser, so
  duplicate keys, NaN, and trailing prose are rejected whatever the provider did.
"""

import json
import os

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from pydantic_ai import Agent, capture_run_messages
from pydantic_ai.exceptions import ContentFilterError, ModelAPIError, UnexpectedModelBehavior
from pydantic_ai.messages import CachePoint, ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings
from pydantic_ai.output import NativeOutput, PromptedOutput, ToolOutput
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider

from maze_lab.agent_contracts import (
    ACTION_MODELS,
    AgentRules,
    AppendNoteFirstTurnAction,
    AppendTurnAction,
    ForcedStayCause,
    InvalidActionError,
    Observation,
    TurnAction,
    parse_turn_action,
)
from maze_lab.config import LlmAgentConfig
from maze_lab.policies.base import DecisionAttempt, Usage
from maze_lab.policies.preflight import check_prompt
from maze_lab.policies.prompt import PROMPT_VERSION, system_instruction, user_blocks

ADAPTER_VERSION = "pydantic_ai_adapter_v1"


def _api_key(config: LlmAgentConfig) -> str | None:
    if config.api_key_env is None:
        return None
    key = os.environ.get(config.api_key_env)
    if not key:
        raise ValueError(f"agent {config.id}: environment variable {config.api_key_env} is not set")
    return key


def build_model(config: LlmAgentConfig) -> Model:
    """Provider model with SDK-level retries switched off."""
    key = _api_key(config)
    if config.provider == "anthropic":
        client = AsyncAnthropic(api_key=key, base_url=config.base_url, max_retries=0)
        return AnthropicModel(config.model, provider=AnthropicProvider(anthropic_client=client))
    # OpenAI, Ollama and OpenRouter all speak the OpenAI chat-completions protocol.
    client = AsyncOpenAI(api_key=key or "unused", base_url=config.base_url, max_retries=0)
    if config.provider == "openrouter":
        return OpenRouterModel(config.model, provider=OpenRouterProvider(openai_client=client))
    return OpenAIChatModel(config.model, provider=OpenAIProvider(openai_client=client))


type _Action = TurnAction | AppendTurnAction | AppendNoteFirstTurnAction


def _output_spec(
    config: LlmAgentConfig, model: type[_Action]
) -> ToolOutput[_Action] | NativeOutput[_Action] | PromptedOutput[_Action]:
    match config.output_mode:
        case "tool":
            return ToolOutput(model, name="submit_action")
        case "native":
            return NativeOutput(model)
        case "prompted":
            return PromptedOutput(model)


def _raw_output(response: ModelResponse | None) -> str | None:
    """The exact action text the model produced: output-tool arguments, else its text."""
    if response is None:
        return None
    for part in response.parts:
        if isinstance(part, ToolCallPart):
            return part.args_as_json_str()
    texts = [p.content for p in response.parts if isinstance(p, TextPart)]
    return "".join(texts) if texts else None


def _usage(responses: list[ModelResponse]) -> Usage:
    reasoning = [r.usage.details.get("reasoning_tokens") for r in responses]
    return Usage(
        input_tokens=sum(r.usage.input_tokens for r in responses),
        output_tokens=sum(r.usage.output_tokens for r in responses),
        reasoning_tokens=sum(x for x in reasoning if x is not None)
        if any(x is not None for x in reasoning)
        else None,
        cache_read_tokens=sum(r.usage.cache_read_tokens for r in responses),
        cache_write_tokens=sum(r.usage.cache_write_tokens for r in responses),
        requests=len(responses),
        estimated_cost_usd=_cost(responses),
    )


def _cost(responses: list[ModelResponse]) -> float | None:
    """The provider's own charge when it reports one (OpenRouter does); otherwise priced from
    usage with the genai-prices table, so cache reads and writes get their own rates."""
    try:
        total = 0.0
        for r in responses:
            billed = (r.provider_details or {}).get("cost")
            total += float(billed) if billed is not None else float(r.cost().total_price)
        return total
    except Exception:  # unknown model in the price table, or no model name
        return None


class _Settings(AnthropicModelSettings, OpenAIChatModelSettings, OpenRouterModelSettings, total=False):
    """Provider settings are key-prefixed, so one dict can carry any provider's options."""


class PydanticAiPolicy:
    def __init__(
        self,
        config: LlmAgentConfig,
        timeout_s: float,
        prompt_version: str = PROMPT_VERSION,
        model: Model | None = None,
        session: str | None = None,
    ) -> None:
        self.config = config
        self.prompt_version = prompt_version
        self.model = model or build_model(config)  # reusable client: allowed, holds no memory
        settings: _Settings = {"max_tokens": config.max_output_tokens, "timeout": timeout_s}
        if config.sampling.temperature is not None:
            settings["temperature"] = config.sampling.temperature
        if config.sampling.top_p is not None:
            settings["top_p"] = config.sampling.top_p
        if config.sampling.seed is not None:
            settings["seed"] = config.sampling.seed
        if session is not None:
            # Groups requests in a Vessel proxy: one session per run, tagged by agent. Others ignore them.
            settings["extra_headers"] = {"X-Vessel-Session": session, "X-Vessel-Tags": config.id}
        if config.provider == "anthropic":
            # Breakpoint after the system instruction; the user prompt adds one after the notebooks.
            # OpenAI-compatible servers and Ollama reuse matching prompt prefixes on their own.
            settings["anthropic_cache_instructions"] = True
            if config.effort in ("low", "medium", "high", "xhigh", "max"):  # config rejects the others
                settings["anthropic_effort"] = config.effort
        if config.provider in ("openai", "ollama") and config.effort is not None:
            settings["openai_reasoning_effort"] = config.effort  # "none" turns reasoning off
        if config.provider == "openrouter":
            settings["openrouter_usage"] = {"include": True}  # report the billed cost of each call
        self.settings = settings

    def request_text(self, system: str, blocks: list[str], action_model: type[_Action] = TurnAction) -> str:
        """Everything sent to the provider, for the invocation record."""
        return json.dumps(
            {
                "system": system,
                "user_blocks": blocks,
                "cache_breakpoint_after_block": 1,
                "output_mode": self.config.output_mode,
                "output_schema": action_model.model_json_schema(),
                "settings": self.settings,
            },
            ensure_ascii=False,
        )

    async def decide(self, observation: Observation, rules: AgentRules) -> DecisionAttempt:
        system = system_instruction(rules, observation.agent_id, self.prompt_version)
        blocks = user_blocks(observation, rules.notebook_ops)
        action_model: type[_Action] = ACTION_MODELS[rules.notebook_ops]
        if self.config.action_field_order == "note_first":
            action_model = AppendNoteFirstTurnAction  # only the requested key order changes
        request_text = self.request_text(system, blocks, action_model)
        if (too_big := check_prompt(self.config, system, blocks)) is not None:
            # Never send a prompt a provider might truncate; this is a forced no-op, not a request.
            return DecisionAttempt(
                action=None, failure="provider_error", request_text=request_text, error_detail=too_big
            )

        output = _output_spec(self.config, action_model)
        agent = Agent(self.model, output_type=output, instructions=system, retries=0)
        failure: ForcedStayCause | None = None
        detail: str | None = None
        messages: list[ModelMessage]
        with capture_run_messages() as messages:
            try:
                prompt = [blocks[0], blocks[1], CachePoint(), blocks[2]]  # stable blocks, then volatile
                await agent.run(prompt, model_settings=self.settings)
            except ContentFilterError as e:
                failure, detail = "refusal", str(e)
            except UnexpectedModelBehavior as e:
                failure, detail = "invalid_action", str(e)
            except (ModelAPIError, OSError, TimeoutError) as e:
                failure, detail = "provider_error", f"{type(e).__name__}: {e}"

        responses = [m for m in messages if isinstance(m, ModelResponse)]
        last = responses[-1] if responses else None
        raw = _raw_output(last)
        action: TurnAction | AppendTurnAction | None = None
        truncated = last is not None and last.finish_reason == "length"
        if truncated and failure in (None, "invalid_action"):
            # Hidden reasoning counts against max_tokens and can leave the action cut off.
            failure, detail = "invalid_action", "output truncated at max_tokens"
        elif failure is None:
            try:
                action = parse_turn_action(raw or "", rules.notebook_ops)
            except InvalidActionError as e:
                failure, detail = "invalid_action", str(e)

        return DecisionAttempt(
            action=action,
            failure=failure,
            request_text=request_text,
            response_text=raw,
            provider_request_id=last.provider_response_id if last else None,
            usage=_usage(responses),
            error_detail=detail,
        )
