from phone_use.agent import AgentLoop, flatten_ui_hierarchy
from phone_use.llm import MockLLM
from phone_use.safety import CaptchaGuard, SafetyPolicy

from fake_device import FakeDevice, ui

HOME = ui("Settings|Open settings|com.android:id/settings|[60,120][300,180]",
          "Chrome|Browser|com.android.chrome:id/icon|[60,220][300,280]")
SETTINGS = ui("Battery|Battery settings||[0,400][1080,500]")


def make_loop(replies, screens, **kwargs):
    device = FakeDevice(screens)
    llm = MockLLM(replies)
    loop = AgentLoop(device=device, llm=llm,
                     guard=CaptchaGuard(), policy=SafetyPolicy(),
                     **kwargs)
    return loop, device, llm


def test_happy_path_tap_then_done():
    loop, device, _ = make_loop(
        ['{"action": "tap", "x": 180, "y": 150}',
         '{"action": "done", "summary": "opened settings"}'],
        [HOME, SETTINGS])
    result = loop.run("open settings")
    assert result.status == "done"
    assert result.summary == "opened settings"
    assert device.actions == [("tap", 180, 150)]


def test_captcha_screen_forces_handoff_before_model_acts():
    captcha = ui("I'm not a robot|||")
    loop, device, llm = make_loop(
        ['{"action": "tap", "x": 1, "y": 1}'], [captcha])
    result = loop.run("log in to example site")
    assert result.status == "handoff"
    assert device.actions == []      # nothing executed on the device
    assert llm.calls == []           # model never even consulted


def test_handoff_callback_fires_with_evidence():
    seen = []
    loop, _, _ = make_loop(
        ['{"action": "done", "summary": "x"}'],
        [ui("reCAPTCHA verify|||")],
        on_handoff=seen.append)
    result = loop.run("anything")
    assert result.status == "handoff"
    assert seen and seen[0].evidence


def test_agent_voluntary_handoff():
    loop, device, _ = make_loop(
        ['{"action": "handoff", "summary": "login needs the owner"}'],
        [HOME])
    result = loop.run("log in for me")
    assert result.status == "handoff"
    assert "login needs the owner" in result.summary
    assert device.actions == []


def test_malformed_reply_gets_one_retry_then_recovers():
    loop, device, _ = make_loop(
        ["let me think about this...",
         '{"action": "key", "key": "HOME"}',
         '{"action": "done", "summary": "went home"}'],
        [HOME, HOME])
    result = loop.run("go home")
    assert result.status == "done"
    assert device.actions == [("key", "HOME")]


def test_persistent_garbage_aborts():
    loop, _, _ = make_loop(["junk", "junk", "junk"], [HOME, HOME, HOME])
    result = loop.run("task")
    assert result.status == "aborted"


def test_step_limit_aborts():
    replies = ['{"action": "wait", "ms": 1}'] * 5
    loop, _, _ = make_loop(replies, [HOME] * 5, max_steps=3)
    result = loop.run("loop forever")
    assert result.status == "aborted"
    assert "step limit" in result.summary


def test_protected_app_blocks_action_mid_loop():
    loop, device, _ = make_loop(
        ['{"action": "tap", "x": 5, "y": 5}'],
        [ui("Pay now|||")])
    loop.device._foreground = "com.paypal.android.p2pmobile"
    result = loop.run("send money")
    assert result.status == "handoff"
    assert device.actions == []


def test_flatten_ui_hierarchy_extracts_centers():
    text = flatten_ui_hierarchy(HOME)
    assert "Settings" in text and "180,150" in text


def test_flatten_handles_broken_xml():
    assert "not xml" in flatten_ui_hierarchy("not xml at all")
