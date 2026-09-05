# Threads of Reasoning

## Overview

Threads model engineering investigation as ordered traversal through viewpoints. Inspired by Gerrit Müller's CAFCR (Cognitive Approach for Flexibly Coordinating Reasoning).

## Viewpoints

Each step in a thread operates from a specific viewpoint:

- `conceptual` — What are we trying to achieve?
- `functional` — What must the system do?
- `realization` — How is it built?
- `application` — How is it used?

## Thread Structure

A Thread has:
- Origin tension (what conflict triggered the investigation)
- Originating question
- Reasoning mode (forward / backward / abductive)
- Ordered steps (examine, hypothesize, validate, conclude)
- Viewpoint sequence (which viewpoints were traversed)
- Optional conclusion (decision, hypothesis, or deferred)

## Transition Rules

Steps transition between viewpoints following CAFCR constraints:
- A hypothesis step requires prior examination
- A validation step requires a hypothesis
- A conclusion requires validation or accepted assumptions

## Implementation

`RuleEngineReasoner` implements these rules deterministically. The `OrchestrationEngine` mediates between agent proposals and thread progression.
