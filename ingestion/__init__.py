"""Tier-3: an agentic, near-zero-cost, multimodal ingestion pipeline.

Discovers open-access quant-finance research (arXiv q-fin), fetches the raw PDFs,
parses text + tables + images + formulas, enriches and quality-gates each document
with bounded LLM agents, and indexes the survivors into Qdrant — all orchestrated as a
LangGraph StateGraph with retries, checkpointing and a human approval gate.

Engineered as a proper data platform (medallion bronze/silver/gold, idempotent +
incremental, data contracts, dead-letter quarantine, lineage, Logfire observability),
and deliberately SEPARATE from the serving API so the runtime container stays lean.
"""
