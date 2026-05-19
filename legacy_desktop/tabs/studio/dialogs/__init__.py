"""
Studio Tab Dialogs
"""

from legacy_desktop.tabs.studio.dialogs.prompt_dialog import PromptSettingDialog
from legacy_desktop.tabs.studio.dialogs.detached_textedit_dialog import DetachedTextEditDialog
from legacy_desktop.tabs.studio.dialogs.export_dialog import ExportViewsDialog
from legacy_desktop.tabs.studio.dialogs.save_preset_dialog import SavePresetDialog
from legacy_desktop.tabs.studio.dialogs.open_preset_dialog import OpenPresetDialog
from legacy_desktop.tabs.studio.dialogs.events_dialog import EventsDialog
from legacy_desktop.tabs.studio.dialogs.preview_dialog import PreviewDialog
from legacy_desktop.tabs.studio.dialogs.sequence_text_dialog import SequenceTextDialog

__all__ = [
    'PromptSettingDialog',
    'DetachedTextEditDialog',
    'ExportViewsDialog',
    'SavePresetDialog',
    'OpenPresetDialog',
    'EventsDialog',
    'PreviewDialog',
    'SequenceTextDialog'
]
