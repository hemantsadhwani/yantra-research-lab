"""What each agent returns. Structured, validated, and then clamped by code: an agent's output
is a proposal, never an instruction the engine obeys blindly."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Style = Literal["continuation", "reversal", "pullback", "unsure"]


class StrategySpec(BaseModel):
    """Intake: the idea, made testable."""
    style: Style
    indicators: list[str] = Field(default_factory=list, description="e.g. EMA, RSI, Bollinger, Donchian, Fibonacci")
    filters_wanted: list[Literal["trend", "vix", "atr_stop"]] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list, max_length=3,
                                 description="only what is missing to test the idea; empty when complete")
    summary: str = Field(description="the idea in one testable sentence")


class Plan(BaseModel):
    """Planner: what to test, how much, and what would count as success."""
    hypothesis: str
    templates: list[str] = Field(min_length=1, max_length=3)
    trial_budget: int = Field(ge=20, le=400)
    rounds: int = Field(ge=1, le=6)
    rationale: str


class PlanReview(BaseModel):
    """Critic on the plan."""
    approve: bool
    changes: str = Field(description="what to change if not approved; empty if approved")


class Experiment(BaseModel):
    """One family of parameter sets: a template and the values to try for each parameter."""
    template: str
    params: dict[str, list[float]] = Field(description="parameter -> values to try (must be catalogue values)")
    rationale: str


class RoundProposal(BaseModel):
    """Researcher: the next experiments, and why, from the results so far."""
    diagnosis: str = Field(description="what the results and diagnostics so far say")
    hypothesis: str
    experiments: list[Experiment] = Field(default_factory=list, max_length=3)
    diagnose: list[str] = Field(default_factory=list, max_length=2,
                                description="family ids to run diagnostics on before the next round")
    stop: bool = False
    stop_reason: str = ""


class CriticReview(BaseModel):
    """Critic on a round: is the progress believable?"""
    verdict: Literal["continue", "robustness_check", "stop"]
    concerns: list[str] = Field(default_factory=list, max_length=4)
    check: list[str] = Field(default_factory=list, max_length=2,
                             description="family ids whose parameter neighbourhood must be tested")


class Report(BaseModel):
    """Reporter: plain words; every number must come from the ledger."""
    title: str
    summary: str
    findings: list[str] = Field(max_length=6)
    verdict: str
