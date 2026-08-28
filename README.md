# GenVerify AI

A [GenLayer](https://genlayer.com) Intelligent Contract that performs
**decentralized, AI-powered document verification**.

The contract takes any document (as plain text) and a list of
plain-language requirements, asks GenLayer's LLM validator network to
judge whether the document satisfies them, and reaches on-chain
consensus on a structured JSON verdict — without ever storing the raw
document itself.

```
Document:  "Service agreement between Company A and Person B..."

Requirements:
  - "Must contain names of all parties"
  - "Must contain signing date"
  - "Must contain termination conditions"

Verdict:
{
  "status": "PASS",
  "missing_items": [],
  "detected_fields": ["party_names", "signature_date", "termination_clause"],
  "issues": [],
  "explanation": "All requested requirements were found"
}
```

## Why this is interesting

Traditional smart contracts can only check things a deterministic
virtual machine can compute — hashes, signatures, numeric conditions.
They can't read a contract in English and tell you whether it actually
covers termination clauses. GenLayer's validator network can run an
LLM and reach **Byzantine consensus on the LLM's judgment**, which is
exactly what this contract puts to use: decentralized, AI-based
judgment over unstructured, real-world documents.

## What it does

- Accepts a document as text plus an arbitrary list of plain-language
  requirements — it is a **generic** verification engine, not tied to
  any one document type (legal agreements, invoices, applications,
  compliance documents, forms, ...).
- Builds a prompt that treats the document as untrusted, inert data
  (resistant to prompt injection — see [Security](#security) below).
- Runs the LLM analysis through GenLayer's non-deterministic execution
  primitive and reaches validator consensus on a structured verdict
  (see [Consensus design](#consensus-design)).
- Stores **only a hash of the document** plus the verdict on-chain —
  never the raw document text.
- Never breaks consensus on malformed LLM output: it falls back to a
  fixed, deterministic `NEEDS_REVIEW` result instead.

**What it deliberately does not do:** no reputation system, no points,
no scores, no rankings, no trust levels, no token rewards, no user
ratings. Its only job is document analysis and verification.

## Contract interface

### `verify_document(document_text: str, requirements: list[str]) -> dict`

The main entry point. Validates the input, runs the AI analysis,
reaches consensus, stores the result, and returns:

```json
{
  "status": "PASS | FAIL | NEEDS_REVIEW",
  "missing_items": ["..."],
  "detected_fields": ["..."],
  "issues": ["..."],
  "explanation": "..."
}
```

Input limits: documents up to 10,000 characters, up to 50
requirements, neither may be empty.

### `get_last_result() -> dict`

Read-only. Returns the last stored verdict in the same shape as above.

### `get_verification_count() -> int`

Read-only. Number of documents processed so far.

### `get_last_document_hash() -> str`

Read-only. The `0x`-prefixed Keccak-256 hash of the last document
analyzed — this is the only trace of the document that ever touches
chain state.

### `get_owner() -> address`

Read-only. The address that deployed the contract. Kept for
provenance/reference only — it is never checked or enforced (there is
no owner-only method or access control anywhere in this contract).

## Use cases

- **Legal agreements** — confirm a contract covers the clauses a
  template requires (parties, dates, termination, confidentiality...).
- **Invoices** — confirm required billing fields are present before
  an invoice is accepted downstream.
- **Applications / forms** — confirm a submitted form contains every
  field a program requires before it moves to the next stage.
- **Compliance documents** — check a policy or filing against a
  checklist of mandatory disclosures.
- **Business contracts** — a general-purpose second pair of eyes on
  contract completeness before a human reviews it.

Because requirements are supplied by the caller at call time, the same
deployed contract works as the verification engine for all of the
above — you don't redeploy per document type.

## Consensus design

GenLayer LLM calls are non-deterministic: two honest validators can
phrase the same finding differently. This contract does **not** use
`strict_eq` / exact-output comparison, and it does **not** use a
schema-only validator either (checking only that the leader's JSON
"looks right" is not real consensus — a broken or dishonest leader can
produce well-formed nonsense).

Instead, the validator:

1. Independently re-runs the **same** LLM analysis (its own call, not
   a copy of the leader's).
2. Requires both runs to structurally validate (correct JSON shape,
   valid `status` enum, string arrays, etc.).
3. Requires the two independent runs to substantively agree:
   - `status` must match **exactly** (`PASS` / `FAIL` / `NEEDS_REVIEW`).
   - `missing_items`, `detected_fields`, and `issues` must match as
     **normalized sets** — case/whitespace-insensitive and
     order-independent, but the actual claims made must be the same.
4. Only `explanation` (a free-text prose summary) is excluded from
   comparison, since two honest LLM calls can phrase an identical
   finding in different words.

**Why sets, and why not skip content entirely.** An earlier version of
this contract only compared `status`, on the theory that comparing
free-text fields would cause false disagreement between honest
validators. A GenLayer reviewer correctly flagged the resulting gap:
a leader could report the right `status` while fabricating or
materially altering `missing_items` / `detected_fields` — nothing was
checking that content, only its shape. Comparing normalized *sets*
closes that gap (fabricated or substantively different claims are
caught) while still not requiring array ordering or exact wording to
match (an honest difference in phrasing or ordering does not trigger a
false disagreement). To make two independent runs converge reliably
under this stricter check, the prompt also asks the model to reuse the
caller's exact requirement text for `missing_items` (instead of
paraphrasing) and a fixed string for manipulation-attempt issues.

If the LLM ever returns malformed output, both leader and validator
fall back to the same fixed, constant `NEEDS_REVIEW` payload rather
than raising — so a bad LLM response degrades gracefully into a
review flag instead of reverting the transaction or blocking consensus.

**Self-consistency, not just shape.** Passing the JSON schema check
doesn't mean the content is coherent: a response could claim
`"status": "PASS"` while still listing something in `missing_items`,
claim `"FAIL"` without naming any reason, or claim `"PASS"` with an
empty `detected_fields` (impossible, since `requirements` is always
non-empty by validation — a real pass must point to *something* it
found). All three are internally contradictory and are treated
exactly like malformed JSON — they fall back to the same fixed
`NEEDS_REVIEW` payload rather than being accepted at face value.

**Grounded against real input, not just against itself.**
`missing_items` is checked against the caller's actual `requirements`
list — a deterministic input every node already has — not just
against the *other* validator's opinion. A claimed missing item that
doesn't correspond to anything the caller asked about is rejected the
same way malformed output is, even if a single LLM run is internally
consistent about it. This is what lets the prompt's "reuse requirement
text verbatim" instruction (above) actually be enforced, rather than
merely requested.

**Counts matter, not just distinct claims.** The consensus comparison
uses normalized *multisets*, not sets: `["party_names", "party_names"]`
and `["party_names"]` are treated as materially different arrays (a
`frozenset` comparison would have incorrectly collapsed the duplicate
and accepted them as equal).

**A note on `explanation` wording.** Because `explanation` is the only
field excluded from the consensus check, it can never cause a
consensus failure regardless of how differently two models phrase the
same finding — this is a deliberate design choice. `detected_fields`,
`missing_items`, and `issues` are different: they *are* compared (as
normalized sets, see above), because their content is a substantive
claim about the document, not prose. The prompt asks for canonical
`snake_case` field labels (`"agreement_id"`, not
`"Agreement ID: SA-2026-0098"` and not a full sentence) and verbatim
requirement text for `missing_items`, both to keep the output
machine-parseable and to help two independent runs converge on
matching sets.

## Security

- **Prompt injection resistance**: the document and requirements are
  embedded in the LLM prompt as JSON-encoded string literals
  (`json.dumps(...)`), not raw string interpolation, so quotes,
  newlines, or fake "SYSTEM:" markers inside the document can't break
  out of the data section. The prompt also explicitly instructs the
  model to treat the document as inert data and to log (not obey) any
  embedded instructions.
- **Data minimization**: the raw document is never written to storage,
  only its Keccak-256 hash — useful as an integrity/reference check
  without ever persisting potentially sensitive document contents
  on a public chain.
- **No unbounded input**: hard caps on document size (10,000 chars)
  and requirement count (50 items), enforced deterministically before
  any LLM call is made.

## Repository layout

```
contracts/
    document_validator.py      # the intelligent contract
tests/
    direct/
        test_document_validator.py     # fast, in-memory tests (leader path)
    integration/
        test_document_validator.py     # full validator-consensus tests
LICENSE                         # MIT
```

## Running the tests

```bash
pip install genlayer-test

# Fast in-memory tests (leader path, no consensus)
pytest tests/direct/ -v

# Full consensus tests against a real GenVM environment
gltest tests/integration/ -v -s
gltest tests/integration/ -v -s --network localnet
```

## Deploying

Pin your GenVM runner in the contract header (already set) and deploy
with your usual GenLayer tooling (Studio, `genlayer` CLI, or `gltest`
against `localnet`/`testnet`). No constructor arguments are required —
the deployer's address is recorded as `owner` and readable via
`get_owner()`, for reference only (it is not used for any access
control or reputation logic).

**Before resubmitting for review:** make sure the source you deploy is
the exact same file you publish/link (byte-for-byte). A reviewer
diffing the published source against the deployed contract needs them
to match; redeploying from a stale local copy after making changes
here is the most common way for that to drift.

## License

MIT — see [LICENSE](LICENSE).
