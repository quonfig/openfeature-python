from openfeature.flag_evaluation import ErrorCode
from quonfig.exceptions import (
    QuonfigInitTimeoutError,
    QuonfigKeyNotFoundError,
    QuonfigNotInitializedError,
)

from quonfig_openfeature.errors import to_error_code


def test_quonfig_key_not_found_maps_to_flag_not_found():
    assert to_error_code(QuonfigKeyNotFoundError("nope")) == ErrorCode.FLAG_NOT_FOUND


def test_quonfig_init_timeout_maps_to_provider_not_ready():
    assert to_error_code(QuonfigInitTimeoutError("slow")) == ErrorCode.PROVIDER_NOT_READY


def test_quonfig_not_initialized_maps_to_provider_not_ready():
    assert to_error_code(QuonfigNotInitializedError("not yet")) == ErrorCode.PROVIDER_NOT_READY


def test_no_value_found_message_maps_to_flag_not_found():
    assert to_error_code(Exception('No value found for key "my-flag"')) == ErrorCode.FLAG_NOT_FOUND


def test_flag_not_found_message_maps_to_flag_not_found():
    assert to_error_code(Exception("flag not found: my-flag")) == ErrorCode.FLAG_NOT_FOUND


def test_type_mismatch_message_maps_to_type_mismatch():
    assert to_error_code(Exception("type mismatch: expected boolean")) == ErrorCode.TYPE_MISMATCH


def test_type_error_maps_to_type_mismatch():
    assert to_error_code(TypeError("nope")) == ErrorCode.TYPE_MISMATCH


def test_not_initialized_message_maps_to_provider_not_ready():
    assert (
        to_error_code(Exception("[quonfig] Not initialized. Call init() first."))
        == ErrorCode.PROVIDER_NOT_READY
    )


def test_provider_not_ready_message_maps_to_provider_not_ready():
    assert to_error_code(Exception("provider not ready")) == ErrorCode.PROVIDER_NOT_READY


def test_unknown_message_maps_to_general():
    assert to_error_code(Exception("some unexpected failure")) == ErrorCode.GENERAL


def test_case_insensitive():
    assert to_error_code(Exception("Flag NOT FOUND")) == ErrorCode.FLAG_NOT_FOUND
    assert to_error_code(Exception("TYPE MISMATCH")) == ErrorCode.TYPE_MISMATCH
