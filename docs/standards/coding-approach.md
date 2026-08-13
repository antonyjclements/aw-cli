---
title: Coding Approach
tags:
  - implementation
  - simplicity
  - code-quality
file-globs:
  - "**/*"
---

# Coding Approach

Rules for avoiding the most common over-engineering and scoping mistakes. Apply during implementation, review, and debugging.

## Simplicity First

Write the minimum code that solves the problem. Nothing speculative.

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that was not requested.
- No error handling for scenarios that cannot happen.
- If you write 200 lines and it could be 50, rewrite it.

Ask: would a senior engineer call this overcomplicated? If yes, simplify.

## Surgical Changes

Touch only what is required. Clean up only your own mess.

When editing existing code:
- Do not improve adjacent code, comments, or formatting unless asked.
- Do not refactor things that are not broken.
- Match existing style, even if you would do it differently.
- If you notice unrelated dead code, mention it — do not delete it.

When your changes create orphans:
- Remove imports, variables, and functions that your changes made unused.
- Do not remove pre-existing dead code unless explicitly asked.

Every changed line should trace directly to the user's request.

## Think Before Coding

State assumptions explicitly before implementing.

- If multiple interpretations exist, present them rather than picking silently.
- If a simpler approach exists, say so and push back when warranted.
- If something is genuinely unclear, name what is confusing and ask before starting.

## Verify Before Finishing

Transform vague tasks into verifiable goals.

- "Add validation" → "Write tests for invalid inputs, then make them pass."
- "Fix the bug" → "Write a test that reproduces it, then make it pass."

For multi-step tasks, state a brief plan with a verification step for each stage before coding.
