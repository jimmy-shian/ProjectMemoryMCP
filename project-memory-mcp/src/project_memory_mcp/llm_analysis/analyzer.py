"""LLM Analyzer - performs structured LLM analysis on code elements."""

import hashlib
import json
import logging
from typing import Any

import instructor
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from project_memory_mcp.llm_analysis.schemas import (
    BUILTIN_PROMPTS,
    AnalysisResult,
    AnalysisStatus,
    DeleteSafetyResult,
    DependencyAnalysisResult,
    EquationAnalysisResult,
    # Output schemas
    FileAnalysisResult,
    ImpactAnalysisResult,
    PromptTemplate,
    SymbolAnalysisResult,
    VariableAnalysisResult,
)
from project_memory_mcp.utils.config import get_settings

logger = logging.getLogger(__name__)

# Schema mapping
SCHEMA_MAP = {
    "FileAnalysisResult": FileAnalysisResult,
    "SymbolAnalysisResult": SymbolAnalysisResult,
    "EquationAnalysisResult": EquationAnalysisResult,
    "VariableAnalysisResult": VariableAnalysisResult,
    "DependencyAnalysisResult": DependencyAnalysisResult,
    "ImpactAnalysisResult": ImpactAnalysisResult,
    "DeleteSafetyResult": DeleteSafetyResult,
}


class LLMAnalyzer:
    """
    Performs LLM-based analysis of code elements with structured output validation.

    Features:
    - Uses instructor for automatic Pydantic validation and retry
    - Supports multiple LLM providers (Anthropic, OpenAI, Google)
    - Agent-driven mode (MCP server generates prompts, Agent fills in)
    - Server-driven mode (MCP server calls LLM directly)
    - Confidence scoring with self-consistency
    - Cost tracking
    """

    def __init__(self, mode: str = "agent_driven"):
        """
        Initialize the LLM analyzer.

        Args:
            mode: "agent_driven" or "server_driven"
        """
        self.mode = mode
        self.settings = get_settings()
        self._client = None
        self._initialize_client()

    def _initialize_client(self) -> None:
        """Initialize the LLM client based on configuration."""
        if self.mode == "server_driven":
            # Initialize instructor client with the configured provider
            provider = self.settings.llm_provider.lower()
            api_key = self.settings.llm_api_key
            model = self.settings.llm_model

            if provider == "anthropic":
                import anthropic
                base_client = anthropic.AsyncAnthropic(api_key=api_key)
                self._client = instructor.from_anthropic(base_client)
            elif provider == "openai":
                import openai
                base_client = openai.AsyncOpenAI(api_key=api_key)
                self._client = instructor.from_openai(base_client)
            elif provider == "google":
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                # Note: instructor doesn't have native Google support yet
                # Use openai-compatible endpoint or raw API
                self._client = None
            elif provider == "myself":
                # Custom OpenAI-compatible endpoint (e.g., local LLM server)
                import openai
                api_base = getattr(self.settings, "llm_api_base", "http://localhost:4000/v1")
                base_client = openai.AsyncOpenAI(api_key=api_key, base_url=api_base)
                self._client = instructor.from_openai(base_client)
            else:
                logger.warning(f"Unknown LLM provider: {provider}")

    def get_prompt(self, prompt_name: str) -> PromptTemplate | None:
        """Get a built-in prompt template."""
        return BUILTIN_PROMPTS.get(prompt_name)

    def list_prompts(self) -> list[str]:
        """List all available prompt templates."""
        return list(BUILTIN_PROMPTS.keys())

    def format_prompt(self, prompt_name: str, **kwargs) -> str:
        """
        Format a prompt template with the given parameters.

        Returns:
            Formatted user prompt string
        """
        template = self.get_prompt(prompt_name)
        if not template:
            raise ValueError(f"Unknown prompt: {prompt_name}")

        # Format the user prompt template
        return template.user_prompt_template.format(**kwargs)

    def get_system_prompt(self, prompt_name: str) -> str:
        """Get the system prompt for a template."""
        template = self.get_prompt(prompt_name)
        if not template:
            raise ValueError(f"Unknown prompt: {prompt_name}")
        return template.system_prompt

    def get_output_schema(self, prompt_name: str) -> type[BaseModel]:
        """Get the output schema class for a prompt."""
        template = self.get_prompt(prompt_name)
        if not template:
            raise ValueError(f"Unknown prompt: {prompt_name}")
        schema_class = SCHEMA_MAP.get(template.output_schema)
        if not schema_class:
            raise ValueError(f"Unknown schema: {template.output_schema}")
        return schema_class

    def create_analysis_task(
        self,
        task_id: str,
        task_type: str,
        target_path: str,
        target_name: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Create an analysis task for agent-driven mode.

        Returns:
            Dictionary with task info and formatted prompt
        """
        prompt_name = f"analyze_{task_type}"
        template = self.get_prompt(prompt_name)

        if not template:
            raise ValueError(f"No prompt template for task type: {task_type}")

        # Build context for the prompt
        prompt_context = context or {}
        prompt_context.setdefault("task_id", task_id)
        prompt_context.setdefault("task_type", task_type)
        prompt_context.setdefault("target_path", target_path)
        prompt_context.setdefault("target_name", target_name)

        formatted_prompt = self.format_prompt(prompt_name, **prompt_context)

        return {
            "task_id": task_id,
            "task_type": task_type,
            "target_path": target_path,
            "target_name": target_name,
            "prompt_name": prompt_name,
            "prompt_version": template.version,
            "system_prompt": template.system_prompt,
            "user_prompt": formatted_prompt,
            "output_schema": template.output_schema,
            "context_hash": self._hash_context(prompt_context),
        }

    def _hash_context(self, context: dict[str, Any]) -> str:
        """Create a hash of the context for caching/deduplication."""
        content = json.dumps(context, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
    )
    async def analyze(
        self,
        prompt_name: str,
        context: dict[str, Any],
        n_consistency: int = 1,
    ) -> AnalysisResult:
        """
        Perform LLM analysis with structured output validation.

        Args:
            prompt_name: Name of the prompt template to use
            context: Context variables for the prompt
            n_consistency: Number of times to run for self-consistency (default 1)

        Returns:
            AnalysisResult with validated output
        """
        if self.mode == "agent_driven":
            raise RuntimeError("In agent-driven mode, use create_analysis_task() and submit results via MCP tool")

        if not self._client:
            raise RuntimeError("LLM client not initialized. Check server_driven config.")

        template = self.get_prompt(prompt_name)
        if not template:
            raise ValueError(f"Unknown prompt: {prompt_name}")

        schema_class = self.get_output_schema(prompt_name)

        # Format prompt
        user_prompt = self.format_prompt(prompt_name, **context)

        # Run analysis (with self-consistency if n_consistency > 1)
        if n_consistency > 1:
            results = []
            for _ in range(n_consistency):
                result = await self._single_analysis(
                    template.system_prompt,
                    user_prompt,
                    schema_class,
                    template.output_schema,
                )
                if result:
                    results.append(result)

            # Aggregate results (simple majority vote for enums, average for floats)
            final_result = self._aggregate_results(results, schema_class)
            confidence = self._calculate_consistency_confidence(results)
        else:
            final_result = await self._single_analysis(
                template.system_prompt,
                user_prompt,
                schema_class,
                template.output_schema,
            )
            confidence = final_result.confidence if final_result else 0.0

        return AnalysisResult(
            task_id=context.get("task_id", "unknown"),
            task_type=prompt_name.replace("analyze_", ""),
            target_path=context.get("target_path", ""),
            target_name=context.get("target_name"),
            result=final_result.model_dump() if final_result else {},
            status=AnalysisStatus.COMPLETED if final_result else AnalysisStatus.FAILED,
            confidence=confidence,
            model_used=self.settings.llm_model,
            prompt_version=template.version,
        )

    async def _single_analysis(
        self,
        system_prompt: str,
        user_prompt: str,
        schema_class: type[BaseModel],
        schema_name: str,
    ) -> BaseModel | None:
        """Run a single LLM analysis call."""
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            response = await self._client.chat.completions.create(
                model=self.settings.llm_model,
                messages=messages,
                response_model=schema_class,
                max_retries=3,
                temperature=0.1,
            )

            return response
        except Exception as e:
            logger.error(f"LLM analysis failed: {e}")
            return None

    def _aggregate_results(self, results: list[BaseModel], schema_class: type[BaseModel]) -> BaseModel:
        """Aggregate multiple results using simple strategies."""
        if not results:
            return schema_class()

        # For now, return the first result
        # In production, implement proper aggregation
        return results[0]

    def _calculate_consistency_confidence(self, results: list[BaseModel]) -> float:
        """Calculate confidence based on self-consistency."""
        if len(results) <= 1:
            return results[0].confidence if results else 0.0

        # Simple heuristic: if all results are similar, high confidence
        # This is a placeholder - real implementation would compare fields
        return sum(r.confidence for r in results) / len(results) * 0.9

    def validate_agent_result(
        self,
        task_id: str,
        output_schema: str,
        agent_response: dict[str, Any],
    ) -> AnalysisResult:
        """
        Validate an agent's response against the expected schema.

        Used in agent-driven mode when the agent submits analysis results.
        """
        schema_class = SCHEMA_MAP.get(output_schema)
        if not schema_class:
            raise ValueError(f"Unknown schema: {output_schema}")

        try:
            # Validate using Pydantic
            validated = schema_class(**agent_response)
            return AnalysisResult(
                task_id=task_id,
                task_type=output_schema.replace("AnalysisResult", "").lower(),
                target_path="",  # Will be filled by caller
                result=validated.model_dump(),
                status=AnalysisStatus.COMPLETED,
                confidence=validated.confidence,
            )
        except Exception as e:
            logger.error(f"Agent result validation failed: {e}")
            return AnalysisResult(
                task_id=task_id,
                task_type=output_schema.replace("AnalysisResult", "").lower(),
                target_path="",
                result={},
                status=AnalysisStatus.FAILED,
                confidence=0.0,
                error=str(e),
            )

    def estimate_cost(self, prompt_name: str, context: dict[str, Any]) -> float:
        """
        Estimate the cost of an analysis in USD.

        Returns:
            Estimated cost in USD
        """
        # Rough estimation based on token counts
        template = self.get_prompt(prompt_name)
        if not template:
            return 0.0

        user_prompt = self.format_prompt(prompt_name, **context)
        system_prompt = template.system_prompt

        # Rough token estimation (4 chars ≈ 1 token)
        input_tokens = (len(system_prompt) + len(user_prompt)) / 4
        output_tokens = 500  # Estimated output

        # Pricing per 1M tokens (approximate)
        pricing = {
            "claude-3-5-sonnet-20241022": {"input": 3.0, "output": 15.0},
            "claude-3-opus-20240229": {"input": 15.0, "output": 75.0},
            "gpt-4o": {"input": 5.0, "output": 15.0},
            "gpt-4o-mini": {"input": 0.15, "output": 0.6},
            "gemini-1.5-pro": {"input": 3.5, "output": 10.5},
        }

        model_pricing = pricing.get(self.settings.llm_model, {"input": 5.0, "output": 15.0})

        cost = (input_tokens / 1_000_000) * model_pricing["input"] + \
               (output_tokens / 1_000_000) * model_pricing["output"]

        return cost


# Global analyzer instance
_analyzer: LLMAnalyzer | None = None


def get_analyzer(mode: str = "agent_driven") -> LLMAnalyzer:
    """Get the global LLM analyzer instance."""
    global _analyzer
    if _analyzer is None:
        _analyzer = LLMAnalyzer(mode=mode)
    return _analyzer
