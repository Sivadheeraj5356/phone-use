import pytest

from phone_use.actions import parse_action
from phone_use.safety import (CaptchaGuard, HandoffRequired, SafetyPolicy)

CAPTCHA_SCREEN = """
<hierarchy><node text="I'm not a robot" content-desc="" resource-id=""
bounds="[100,200][400,260]"/><node text="reCAPTCHA" content-desc=""
resource-id="" bounds="[100,300][400,340]"/></hierarchy>
"""


class TestCaptchaGuard:
    def test_detects_recaptcha_screen(self):
        guard = CaptchaGuard()
        with pytest.raises(HandoffRequired) as excinfo:
            guard.inspect(CAPTCHA_SCREEN, "com.android.chrome")
        assert excinfo.value.evidence  # carries what it matched

    def test_detects_cloudflare_challenge(self):
        guard = CaptchaGuard()
        with pytest.raises(HandoffRequired):
            guard.inspect("Cloudflare - Verify you are human", "")

    def test_detects_image_selection_challenge(self):
        guard = CaptchaGuard()
        with pytest.raises(HandoffRequired):
            guard.inspect("Select all images with traffic lights", "")

    def test_clean_screen_passes(self):
        guard = CaptchaGuard()
        guard.inspect("Settings | Battery | Display", "com.android.settings")

    def test_extra_pattern(self):
        guard = CaptchaGuard(extra_patterns=[r"\bslide to verify\b"])
        with pytest.raises(HandoffRequired):
            guard.inspect("Please slide to verify", "")


class TestSafetyPolicy:
    def _action(self, blob: str):
        return parse_action(blob)

    def test_payment_app_denied_without_confirmation_callback(self):
        policy = SafetyPolicy()
        with pytest.raises(HandoffRequired):
            policy.check_action(self._action('{"action": "tap", "x": 1, "y": 2}'),
                                foreground_package="com.paypal.android.p2pmobile")
        assert policy.denied_log

    def test_payment_app_asks_confirmation_when_callback_set(self):
        seen = []
        policy = SafetyPolicy(
            require_confirmation=lambda action, reason: seen.append(reason) or True)
        policy.check_action(self._action('{"action": "tap", "x": 1, "y": 2}'),
                            foreground_package="com.paypal.android.p2pmobile")
        assert seen

    def test_declined_confirmation_denies(self):
        policy = SafetyPolicy(require_confirmation=lambda a, r: False)
        with pytest.raises(HandoffRequired):
            policy.check_action(self._action('{"action": "tap", "x": 1, "y": 2}'),
                                foreground_package="com.paypal.android.p2pmobile")

    def test_blocked_package_launch_refused(self):
        policy = SafetyPolicy(blocked_packages=("com.example.bank",))
        with pytest.raises(HandoffRequired):
            policy.check_action(
                self._action('{"action": "launch", "package": "com.example.bank"}'))

    def test_normal_app_passes(self):
        policy = SafetyPolicy()
        policy.check_action(self._action('{"action": "tap", "x": 10, "y": 20}'),
                            foreground_package="com.android.settings")
        assert policy.denied_log == []
