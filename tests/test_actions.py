import pytest

from guardedcoder.errors import ActionParseError
from guardedcoder.models.actions import parse_llm_response


def test_legal_list_dir_parses() -> None:
    action = parse_llm_response('{"action":"list_dir","path":"."}')
    assert action.action == "list_dir"
    assert action.path == "."


def test_unknown_network_action_raises() -> None:
    with pytest.raises(ActionParseError):
        parse_llm_response('{"action":"network"}')


def test_extra_field_raises() -> None:
    with pytest.raises(ActionParseError):
        parse_llm_response('{"action":"list_dir","path":".","extra":true}')


def test_oversized_json_raises() -> None:
    with pytest.raises(ActionParseError):
        parse_llm_response("x" * 1_000_001)
