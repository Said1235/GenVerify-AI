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
3. Requires the two independent runs to agree **exactly on `status`**
   (`PASS` / `FAIL` / `NEEDS_REVIEW`) — the one field that actually
   matters for a downstream consumer's decision.
4. Deliberately does **not** compare `explanation` wording, `issues`
   phrasing, or array ordering between the two runs, since two honest
   LLM calls can describe an identical finding in different words.

If the LLM ever returns malformed output, both leader and validator
fall back to the same fixed, constant `NEEDS_REVIEW` payload rather
than raising — so a bad LLM response degrades gracefully into a
review flag instead of reverting the transaction or blocking consensus.

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

Both suites were run against the exact `py-genlayer` runtime this
contract's header pins (`py-genlayer:1jb45aa8yn...`, from
[GenLayer's `genvm` releases](https://github.com/genlayerlabs/genvm))
before this repository was published, exercising: `PASS` / `FAIL` /
`NEEDS_REVIEW` outcomes, prompt-injection attempts, empty/oversized
inputs, malformed LLM output recovery, validator agreement /
disagreement, and hash-only storage.

## Deploying

Pin your GenVM runner in the contract header (already set) and deploy
with your usual GenLayer tooling (Studio, `genlayer` CLI, or `gltest`
against `localnet`/`testnet`). No constructor arguments are required —
the deployer's address is recorded as `owner` for reference only (it
is not used for any access control or reputation logic).

## License

MIT — see [LICENSE](LICENSE).
