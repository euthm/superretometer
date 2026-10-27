# One public toolchain smoke test: CH + Harness2 + Julia boundary

Review one PR and run one command after optional dependency setup. No private
repository, AI1, Memory, StrategyServer, OpenCode or model account is needed for
the default test. The example does not modify CH core, specs, gates or MCP.

## Setup once

Use Python 3.12 or 3.13 (upstream H2 requires >=3.12,<3.14), preferably in your
own virtual environment. From the Superretometer checkout:

```sh
python3 -m pip install -r examples/toolchain_pilot/requirements.txt
```

This explicitly installs H2 from pinned upstream commit
1cfe254e8d25b15f37048c3730134686abe60335. It is an optional example dependency,
not a new Superretometer base dependency. Setup needs network; the default
smoke run makes no model or advisory network request. No model weights install.

## Run

```sh
python3 examples/toolchain_pilot/run.py
```

The command prints one report and saves it with all supporting artifacts to a
new toolchain-report-* directory. Use --output <new-directory> to choose the
location. It never overwrites or resumes an existing evidence directory.

Expected sections:

| Section | Expected outcome |
|---|---|
| H2 deterministic k=1 workflow | 4 rollouts, 3 scripted proposal stages |
| Original signed-sum bug | 0/2 cases, CH test BLOCK |
| Hardcoded answer mutation | 1/2 cases, CH test BLOCK |
| Composed general signed-sum repair | 2/2 cases, CH test PASS |
| Corrupt saved result | Import rejected |
| Julia boundary controls | Nine controlled checks PASS |
| Live Julia | NOT_RUN unless explicitly configured |
| Adoption/design-bearing | false |

The demo executes actual candidate Python programs and a separate verifier.
It imports verified receipt bytes through ConsumerAPI proposals. Each variant
saves its original CH graph/gates and separate advisory output. The 39 upstream
H2 Python module blobs/inventory are verified before and after execution.
The freeze manifest also records actual CH core/example hashes. Generated
candidate hashes are separate from the upstream workflow Git commit.

The boundary controls deliberately make a model recommend SUPPORT for a
failing candidate: CH must remain BLOCK. They also cover negative advice,
missing score, malformed response, timeout and absent endpoint. Responses are
controlled stubs, NOT observations from a real Julia model. Advisory output is
never inserted as a SUPPORTS relation or independent evidence root and cannot
modify the gate report or grant execution authority.

## Optional real Julia

With your own already-running local compatible endpoint:

```sh
python3 examples/toolchain_pilot/run.py --julia-url http://127.0.0.1:8011/v1/systemone
```

No server is installed or started by this example. The experimental adapter
expects the state/questions request and answers.q1.noul numeric response
contract; verify compatibility with your Julia deployment. Missing/invalid
scores yield UNKNOWN, network failure yields NOT_RUN, with no retry loop or
automatic positive default. Timeout is one second, response bound 16 KiB,
redirects disabled, endpoint restricted to local HTTP without credentials.
This is endpoint validation, not a complete network isolation mechanism.

The report distinguishes offline_integration from live_julia. Explicitly
requested live checks give exit 2 if incomplete and exit 1 if valid labels
disagree with the three fixed expected classifications. An incorrect Julia
classification never changes CH's test outcome. Default exit 0 means the
offline smoke controls passed; it does not mean live Julia ran.

For an existing pinned source export, pass --harness2-source <checkout> instead
of installing H2. For the test suite, set HARNESS2_SOURCE to that checkout or
install the optional dependency, then run python3 -m pytest tests/ -v. Without
H2, only its optional integration test is explicitly skipped, never fabricated
as a passing H2 run. A missing H2 in the smoke command gives INCOMPLETE/exit 2.

## Scope and interpretation

This is a synthetic public integration control, not the private HRRM simulator
or a model coding benchmark. Upstream DemoProposer has predetermined edits; no
LLM performs discovery or optimization. Existing visible fixtures are not a
hidden holdout. Missing worktree/freshness observations remain UNKNOWN. Warrant
is computed separately from the test gate. Receipt hashes verify byte integrity
relative to caller pins, not producer authenticity or truth of supplied data.
No automatic adoption, library update or live MCP persistence is implemented.

The optional offline bridge is documented in ../harness2_bridge/README.md.
All example fixtures are synthetic and no private project code is published.
