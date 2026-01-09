"""
Studio Tab Dialogs
"""

from tabs.studio.dialogs.prompt_dialog import PromptSettingDialog
from tabs.studio.dialogs.detached_textedit_dialog import DetachedTextEditDialog
from tabs.studio.dialogs.export_dialog import ExportViewsDialog
from tabs.studio.dialogs.save_preset_dialog import SavePresetDialog
from tabs.studio.dialogs.open_preset_dialog import OpenPresetDialog
from tabs.studio.dialogs.events_dialog import EventsDialog
from tabs.studio.dialogs.preview_dialog import PreviewDialog
from tabs.studio.dialogs.sequence_text_dialog import SequenceTextDialog

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
