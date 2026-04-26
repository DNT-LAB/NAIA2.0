"""
DPI size compatibility helpers.

future01 removes user-configurable UI scaling. Existing widgets still call these
helpers widely, so this module keeps the API stable while returning the original
sizes unchanged.
"""

from PyQt6.QtCore import QObject, pyqtSignal


class ScalingManager(QObject):
    """Compatibility shim for the removed scaling feature."""

    scaling_changed = pyqtSignal(float)

    def __init__(self):
        super().__init__()
        self._current_scale = 1.0

    def calculate_scale_factor(self):
        """Keep a fixed scale factor."""
        self._current_scale = 1.0

    def get_scale_factor(self):
        """Return the fixed compatibility scale factor."""
        return self._current_scale

    def get_scaled_size(self, base_size):
        """Return the original size."""
        return int(base_size)

    def get_scaled_font_size(self, base_font_size):
        """Return the original font size with the historical lower bound."""
        return max(8, int(base_font_size))

    def set_user_scale_factor(self, _factor):
        """No-op kept for older callers."""
        self.scaling_changed.emit(self._current_scale)

    def set_auto_scaling_enabled(self, _enabled):
        """No-op kept for older callers."""
        self.scaling_changed.emit(self._current_scale)

    def is_auto_scaling_enabled(self):
        """Compatibility value for older callers."""
        return False

    def get_user_scale_factor(self):
        """Compatibility value for older callers."""
        return self._current_scale

    def save_settings(self):
        """No-op: scaling settings are no longer persisted."""

    def load_settings(self):
        """No-op: scaling settings are no longer loaded."""

    def refresh_scaling(self):
        """Emit the fixed scale for older listeners."""
        self.scaling_changed.emit(self._current_scale)


_scaling_manager = None


def get_scaling_manager():
    """Return the compatibility singleton."""
    global _scaling_manager
    if _scaling_manager is None:
        _scaling_manager = ScalingManager()
    return _scaling_manager


def get_scaled_size(base_size):
    """Return the unscaled size."""
    return get_scaling_manager().get_scaled_size(base_size)


def get_scaled_font_size(base_font_size):
    """Return the unscaled font size."""
    return get_scaling_manager().get_scaled_font_size(base_font_size)


def get_current_scale_factor():
    """Return the fixed compatibility scale factor."""
    return get_scaling_manager().get_scale_factor()
