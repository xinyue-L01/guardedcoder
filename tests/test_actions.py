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


def test_non_string_path_raises() -> None:
    with pytest.raises(ActionParseError):
        parse_llm_response('{"action":"list_dir","path":1}')


def test_oversized_json_raises() -> None:
    raw = '{"action":"list_dir","path":"' + ("a" * 1_000_000) + '"}'
    assert len(raw) > 1_000_000
    with pytest.raises(ActionParseError):
        parse_llm_response(raw)
