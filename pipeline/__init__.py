"""Gist news pipeline.

Stages: ingest -> queue -> store -> select -> create -> check -> deploy -> learn.
Each stage is a pipeline.orchestrator.Stage; the orchestrator runs them and
records a RunReport. Only ingestion (and its queue handoff) exists so far.
"""
