# OpenClaw Billing Guardian

## Purpose

This experiment makes OpenClaw provider billing and account errors understandable to non-expert users. Instead of exposing raw English provider errors or generic failure copy, it formats structured provider/runtime errors into Chinese recovery guidance with the right console entry point.

## Status

`validated`

The experiment has a tested translator module, patch script, verification script, and installer script for a user-level systemd drop-in.

## How to Run

From the repository root:

```bash
npm run test:openclaw-billing-guardian
npm run patch:openclaw-billing -- --dry-run
npm run verify:openclaw-billing
```

From this experiment directory:

```bash
node --test test/*.test.js
node scripts/patch-openclaw-billing-message.mjs --dry-run
node scripts/verify-openclaw-billing-message.mjs
```

## Main Files

```text
src/openclaw-error-translator.js
scripts/patch-openclaw-billing-message.mjs
scripts/verify-openclaw-billing-message.mjs
scripts/install-openclaw-billing-guardian.mjs
test/*.test.js
```

## Lighthouse Relationship

This is an instance-side OpenClaw usability guardrail. It can remain as an operational patch helper, or later become an OpenClaw plugin, gateway feature, or Lighthouse health/remediation workflow.

## Boundary

The translator should only act on provider/runtime error provenance. Conversation text, chat history, and ordinary user messages are not valid billing-error evidence even if they mention `HTTP 402`, `insufficient balance`, or similar keywords.

## Concept Doc

See [../../docs/concepts/openclaw-error-guardian.md](../../docs/concepts/openclaw-error-guardian.md).

## Next Steps

- Add more provider-specific recovery guidance.
- Productize model-account health checks in Lighthouse.
- Replace patching with a supported OpenClaw extension point when available.
