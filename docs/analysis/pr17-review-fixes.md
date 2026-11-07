# PR #17 review fixes

The follow-up corrects proposal restoration, evidence readback, restart-test
isolation, credential handling, counter-evidence registration, and diagnosis.

- Every Proposal field is serialized under its existing `ch_proposal_*` name.
  Enum types, structured values, falsy content, scope, temporal bounds, and
  execution result IDs survive restoration. Legacy partial proposals still load.
- Evidence uses the normal KO identity/lookup path. Claim ID, source KO ID,
  records, and relation type persist. Read/list operations work with empty caches;
  old evidence missing its claim ID recovers the reference from the outgoing edge.
- Restart tests import `transports.*` from the checkout and verify module paths.
  A committed subprocess worker receives credentials through environment variables
  and identifiers through stdin. No credential-bearing scripts are generated.
  Search visibility is checked with a fresh adapter, outside the writer's cache.
- InMemoryStorage's CREATE_EVIDENCE/contradicts path creates the counter-evidence
  KO and edge, so warrant discovers it without a manual create_relation workaround.
  Legacy supporting verification records retain their existing behavior; a full
  unification of record attachment and carrying evidence remains the separate
  CH-EVIDENCE-SEMANTICS decision. They are not interchangeable operations today.
- Generic counter-evidence produces CONTRADICTED, not PHYSICALLY_UNREALIZABLE.
  Conservation-law conflicts retain the latter diagnosis. The normative policy
  and new conformance tests are in spec/WARRANT.md and test_counter_evidence_contract.py.

## Verification boundary

`tests/transport/test_review_regressions.py` uses a local deterministic HTTP
fixture that assigns Memory UUIDs different from CH IDs and persists across
separate adapter/process lifetimes. It does not establish compatibility with a
particular deployed Memory version or verify AI1's copied runtime files.

Local result (Python 3.12, `python -m pytest tests/ -v`): 266 passed, 7 skipped,
including 21 new regression/conformance cases. Six skipped tests require the
explicit live Memory configuration; the remaining skip is an optional toolchain.

Live tests require explicit configuration (credentials stay in the environment):

```bash
MEMORY_LIVE_TESTS=1 python -m pytest tests/transport/test_truth_category_integration.py -v
```

Set MEMORY_SERVER_URL, MEMORY_API_KEY, and MEMORY_PROJECT_ID before this command.
Use the selected project's credentials and run the tests from the repo checkout.
These opt-in tests create persistent test objects in that selected project.
They do not load a user's home configuration or select a project implicitly.
