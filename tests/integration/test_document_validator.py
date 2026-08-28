"""
Integration tests for contracts/document_validator.py

Run with:
    gltest tests/integration/test_document_validator.py -v -s
    gltest tests/integration/test_document_validator.py -v -s --network localnet

These run against a real GenLayer environment (GLSim / Studio local /
localnet) with full leader + validator consensus, using mocked LLM
validators so results are deterministic and repeatable in CI.
"""

import json

from gltest import get_contract_factory, get_validator_factory
from gltest.assertions import tx_execution_succeeded
from gltest.types import MockedLLMResponse

VALID_DOCUMENT = (
    "Service Agreement between Company A and Person B, effective as of "
    "2024-01-15. This agreement terminates automatically after 12 months "
    "or upon 30 days written notice by either party. Signed by both "
    "parties on 2024-01-15."
)

VALID_REQUIREMENTS = [
    "Must contain names of all parties",
    "Must contain signing date",
    "Must contain termination conditions",
]

PASS_JSON = json.dumps(
    {
        "status": "PASS",
        "missing_items": [],
        "detected_fields": ["party_names", "signature_date", "termination_clause"],
        "issues": [],
        "explanation": "All requested requirements were found.",
    }
)

FAIL_JSON = json.dumps(
    {
        "status": "FAIL",
        "missing_items": ["Must contain signing date"],
        "detected_fields": ["party_names"],
        "issues": ["No explicit date found in the document"],
        "explanation": "The document does not state a signing date.",
    }
)


def _mock_validators(count: int, llm_json: str):
    """Create validators whose gl.nondet.exec_prompt calls all return the
    same mocked JSON string, so leader + validators reach consensus."""
    mock_response: MockedLLMResponse = {
        "nondet_exec_prompt": {
            "DOCUMENT_DATA": llm_json,
        }
    }
    validator_factory = get_validator_factory()
    return validator_factory.batch_create_mock_validators(
        count=count, mock_llm_response=mock_response
    )


def test_deploy_and_verify_document_pass():
    validators = _mock_validators(5, PASS_JSON)
    transaction_context = {"validators": [v.to_dict() for v in validators]}

    factory = get_contract_factory("DocumentValidator")
    contract = factory.deploy(transaction_context=transaction_context)

    tx = contract.verify_document(
        args=[VALID_DOCUMENT, VALID_REQUIREMENTS]
    ).transact(transaction_context=transaction_context)

    assert tx_execution_succeeded(tx)

    result = contract.get_last_result().call()
    assert result["status"] == "PASS"

    count = contract.get_verification_count().call()
    assert count == 1


def test_verify_document_fail_on_missing_requirements():
    validators = _mock_validators(5, FAIL_JSON)
    transaction_context = {"validators": [v.to_dict() for v in validators]}

    factory = get_contract_factory("DocumentValidator")
    contract = factory.deploy(transaction_context=transaction_context)

    incomplete_document = "Service Agreement between Company A and Person B."

    tx = contract.verify_document(
        args=[incomplete_document, VALID_REQUIREMENTS]
    ).transact(transaction_context=transaction_context)

    assert tx_execution_succeeded(tx)

    result = contract.get_last_result().call()
    assert result["status"] == "FAIL"
    assert "Must contain signing date" in result["missing_items"]


def test_only_hash_is_persisted_on_chain():
    validators = _mock_validators(5, PASS_JSON)
    transaction_context = {"validators": [v.to_dict() for v in validators]}

    factory = get_contract_factory("DocumentValidator")
    contract = factory.deploy(transaction_context=transaction_context)

    tx = contract.verify_document(
        args=[VALID_DOCUMENT, VALID_REQUIREMENTS]
    ).transact(transaction_context=transaction_context)
    assert tx_execution_succeeded(tx)

    doc_hash = contract.get_last_document_hash().call()
    assert doc_hash.startswith("0x")
    assert VALID_DOCUMENT not in doc_hash


def test_empty_document_transaction_fails_execution():
    validators = _mock_validators(5, PASS_JSON)
    transaction_context = {"validators": [v.to_dict() for v in validators]}

    factory = get_contract_factory("DocumentValidator")
    contract = factory.deploy(transaction_context=transaction_context)

    tx = contract.verify_document(args=["", VALID_REQUIREMENTS]).transact(
        transaction_context=transaction_context
    )

    # ACCEPTED/FINALIZED lifecycle state does not imply execution success -
    # this must be an explicit execution failure, and no state changes
    # (verification_count must remain 0).
    assert not tx_execution_succeeded(tx)

    count = contract.get_verification_count().call()
    assert count == 0
