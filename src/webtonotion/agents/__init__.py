"""Agentic orchestrator layer.

This package holds the multi-turn conversation agent, its dependency-injected
tools, and session storage. Dependency direction is ``api -> agents -> services
-> models/config``; nothing under ``services/`` imports from here.
"""
