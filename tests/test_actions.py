import pytest

from phone_use.actions import ActionError, parse_action


def test_parse_bare_json_tap():
    a = parse_action('{"action": "tap", "x": 540, "y": 1200}')
    assert a.kind == "tap" and (a.x, a.y) == (540, 1200)


def test_parse_inside_markdown_fence():
    reply = 'Here is my move:\n```json\n{"action": "type", "text": "hi there"}\n```'
    a = parse_action(reply)
    assert a.kind == "type" and a.text == "hi there"


def test_parse_embedded_in_prose():
    a = parse_action('I will go back now. {"action": "key", "key": "back"} done.')
    assert a.kind == "key" and a.key == "BACK"


def test_swipe_requires_all_four_points():
    with pytest.raises(ActionError):
        parse_action('{"action": "swipe", "x": 1, "y": 2}')


def test_type_requires_nonempty_text():
    with pytest.raises(ActionError):
        parse_action('{"action": "type", "text": ""}')


def test_launch_requires_package_like_value():
    with pytest.raises(ActionError):
        parse_action('{"action": "launch", "package": "settings"}')
    a = parse_action('{"action": "launch", "package": "com.android.settings"}')
    assert a.package == "com.android.settings"


def test_unknown_action_rejected():
    with pytest.raises(ActionError):
        parse_action('{"action": "delete_everything"}')


def test_garbage_rejected():
    with pytest.raises(ActionError):
        parse_action("I don't know what to do.")


def test_negative_wait_rejected():
    with pytest.raises(ActionError):
        parse_action('{"action": "wait", "ms": -5}')


def test_done_carries_summary():
    a = parse_action('{"action": "done", "summary": "wifi is on"}')
    assert a.kind == "done" and a.summary == "wifi is on"
