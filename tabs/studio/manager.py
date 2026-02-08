"""
ResultImageFrameManager - Grid manager for ResultImageFrame widgets
"""

import json
import os
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QScrollArea, QFrame,
    QMessageBox, QFileDialog, QSizePolicy
)
from PyQt6.QtCore import Qt, QObject, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap
from PIL import Image

from tabs.studio.frame import ResultImageFrame
from tabs.studio.wildcard_mode_state import WildcardModeState, WildcardAxisInfo
from tabs.studio.wildcard_combination_generator import WildcardCombinationGenerator
from ui.theme import DARK_COLORS, get_dynamic_styles, show_info, show_warning, show_error
from ui.scaling_manager import get_scaled_size

if TYPE_CHECKING:
    from core.context import AppContext


class ResultImageFrameManager(QObject):
    """Manager for ResultImageFrame grid layout"""

    # Signals
    generation_started = pyqtSignal()
    generation_stopped = pyqtSignal()
    generation_progress = pyqtSignal(int, int)  # (current, total)
    frame_updated = pyqtSignal(int)  # frame index
    prompt_edit_requested = pyqtSignal(int)  # frame index

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frames: List[ResultImageFrame] = []
        self.grid_layout: Optional[QGridLayout] = None
        self.scroll_widget: Optional[QWidget] = None
        self.app_context: Optional['AppContext'] = None

        # Grid configuration
        self.grid_rows = 3
        self.grid_cols = 4

        # Scroll area reference for viewport calculations
        self.scroll_area: Optional[QScrollArea] = None

        # Frame size uniformity - resize debounce timer
        self._resize_timer = QTimer()
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._recalculate_frame_sizes)
        self._last_viewport_width = 0

        # Cached frame dimensions for new frames
        self._cached_frame_width = 0
        self._cached_frame_height = 0

        # Generation state
        self.is_generating = False
        self.current_event_index = 0
        self.total_events = 0
        self.repeat_count = 1
        self.generation_queue: List[tuple] = []  # (frame_index, repeat_index)

        # Seed fixing state
        self.fix_seed_mode = False
        self.last_generated_seed: Optional[int] = None

        # Wildcard mode state
        self.wildcard_mode_state = WildcardModeState()

    def set_app_context(self, app_context: 'AppContext'):
        """Set AppContext for event communication"""
        self.app_context = app_context

    def eventFilter(self, obj, event):
        """Event filter to detect viewport resize for uniform frame sizing"""
        from PyQt6.QtCore import QEvent

        try:
            if self.scroll_area and obj == self.scroll_area.viewport():
                if event.type() == QEvent.Type.Resize:
                    # Debounce resize events
                    self._resize_timer.start(50)  # 50ms debounce
        except RuntimeError:
            # scroll_area의 C++ 객체가 이미 삭제된 경우 (프로그램 종료 시)
            pass
        return super().eventFilter(obj, event)

    def _recalculate_frame_sizes(self):
        """Recalculate and apply uniform frame sizes based on viewport width"""
        if not self.scroll_area or not self.frames:
            return

        viewport = self.scroll_area.viewport()
        if not viewport:
            return

        viewport_width = viewport.width()

        # Skip if width hasn't changed significantly (within 5px)
        if abs(viewport_width - self._last_viewport_width) < 5:
            return

        self._last_viewport_width = viewport_width

        # Calculate uniform frame size
        spacing = get_scaled_size(8)
        margins = get_scaled_size(8) * 2  # Left + Right margins
        scrollbar_reserve = get_scaled_size(20)  # Reserve space for potential scrollbar

        # Available width for all frames in a row
        available_width = viewport_width - margins - scrollbar_reserve

        # Calculate frame width (accounting for spacing between frames)
        total_spacing = spacing * (self.grid_cols - 1)
        frame_width = (available_width - total_spacing) // self.grid_cols

        # Ensure minimum frame width
        min_width = get_scaled_size(180)
        frame_width = max(frame_width, min_width)

        # Calculate frame height maintaining aspect ratio (roughly 4:5 for portrait-oriented images)
        frame_height = int(frame_width * 1.25)

        # Cache dimensions for new frames
        self._cached_frame_width = frame_width
        self._cached_frame_height = frame_height

        # Apply uniform size to all frames
        for frame in self.frames:
            frame.set_uniform_size(frame_width, frame_height)

    def trigger_frame_resize(self):
        """Public method to trigger frame size recalculation"""
        self._recalculate_frame_sizes()

    def create_grid(self, rows: int = 3, cols: int = 4) -> QWidget:
        """Create scrollable grid of ResultImageFrames"""
        self.grid_rows = rows
        self.grid_cols = cols

        # Create scroll area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: {DARK_COLORS['bg_primary']};
                border: none;
            }}
        """)

        # Container widget for grid
        self.scroll_widget = QWidget()
        self.scroll_widget.setStyleSheet(f"""
            QWidget {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)

        self.grid_layout = QGridLayout(self.scroll_widget)
        self.grid_layout.setSpacing(get_scaled_size(8))
        self.grid_layout.setContentsMargins(
            get_scaled_size(8), get_scaled_size(8),
            get_scaled_size(8), get_scaled_size(8)
        )

        # Create initial frames
        self._create_initial_frames()

        self.scroll_area.setWidget(self.scroll_widget)

        # Install event filter to detect viewport resize
        self.scroll_area.viewport().installEventFilter(self)

        # Schedule initial frame size calculation after layout is complete
        QTimer.singleShot(100, self._recalculate_frame_sizes)

        return self.scroll_area

    def _create_initial_frames(self):
        """Create initial grid of frames"""
        total_frames = self.grid_rows * self.grid_cols

        for i in range(total_frames):
            frame = self._create_frame(i)
            row = i // self.grid_cols
            col = i % self.grid_cols
            self.grid_layout.addWidget(frame, row, col)
            self.frames.append(frame)

    def _create_frame(self, index: int) -> ResultImageFrame:
        """Create a single ResultImageFrame with signal connections"""
        frame = ResultImageFrame(index)

        # Connect signals
        frame.generate_requested.connect(self._on_frame_generate_requested)
        frame.delete_requested.connect(self._on_frame_delete_requested)
        frame.prompt_edit_requested.connect(self._on_frame_prompt_edit_requested)
        frame.save_requested.connect(self._on_frame_save_requested)
        frame.save_all_requested.connect(self._on_frame_save_all_requested)

        return frame

    # === Frame management ===
    def add_frame(self) -> ResultImageFrame:
        """Add a new frame to the grid"""
        index = len(self.frames)
        frame = self._create_frame(index)

        # Apply cached size immediately if available
        if self._cached_frame_width > 0 and self._cached_frame_height > 0:
            frame.set_uniform_size(self._cached_frame_width, self._cached_frame_height)

        row = index // self.grid_cols
        col = index % self.grid_cols
        self.grid_layout.addWidget(frame, row, col)
        self.frames.append(frame)

        # Recalculate sizes after adding frame
        QTimer.singleShot(50, self._recalculate_frame_sizes)

        return frame

    def insert_frame_at(self, position: int) -> ResultImageFrame:
        """Insert a new frame at specific position"""
        # Clamp position
        position = max(0, min(position, len(self.frames)))

        # Create new frame
        frame = self._create_frame(position)

        # Apply cached size immediately if available
        if self._cached_frame_width > 0 and self._cached_frame_height > 0:
            frame.set_uniform_size(self._cached_frame_width, self._cached_frame_height)

        # Insert into list
        self.frames.insert(position, frame)

        # Reorganize grid with updated indices
        self._reorganize_grid()

        return frame

    def remove_frame(self, index: int):
        """Remove frame at index (reset if last one)"""
        if index < 0 or index >= len(self.frames):
            return

        if len(self.frames) <= 1:
            # Reset instead of remove if it's the last frame
            self.frames[0].reset()
            return

        # Remove frame
        frame = self.frames.pop(index)
        self.grid_layout.removeWidget(frame)
        frame.deleteLater()

        # Reorganize grid
        self._reorganize_grid()

    def _reorganize_grid(self):
        """Reorganize grid after frame removal"""
        # Clear layout
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            # Don't delete widgets, just remove from layout

        # Re-add frames with updated indices
        for i, frame in enumerate(self.frames):
            frame.index = i
            row = i // self.grid_cols
            col = i % self.grid_cols
            self.grid_layout.addWidget(frame, row, col)
            frame.show()

        # Recalculate sizes after reorganization
        QTimer.singleShot(50, self._recalculate_frame_sizes)

    def get_frame(self, index: int) -> Optional[ResultImageFrame]:
        """Get frame by index"""
        if 0 <= index < len(self.frames):
            return self.frames[index]
        return None

    def get_active_frames(self) -> List[ResultImageFrame]:
        """Get frames that have prompts configured"""
        return [f for f in self.frames if f.has_prompt() and f.prompt_data.get('enabled', True)]

    def get_total_event_count(self) -> int:
        """Get count of active frames"""
        return len(self.get_active_frames())

    # === Signal handlers ===
    def _on_frame_generate_requested(self, index: int):
        """Handle single frame generation request"""
        # Prevent generation if already generating
        if self.is_generating:
            return

        frame = self.get_frame(index)
        if frame and frame.has_prompt():
            # Lock all frames during single generation
            self._lock_all_frames()

            # Single frame generation will be handled by StudioTab
            print(f"Generation requested for frame #{index + 1}")
            self.frame_updated.emit(index)

    def _lock_all_frames(self):
        """Lock all frame generation buttons and emit started signal"""
        self.is_generating = True
        for frame in self.frames:
            frame.set_generating_state(True)
        self.generation_started.emit()

    def _unlock_all_frames(self):
        """Unlock all frame generation buttons and emit stopped signal"""
        self.is_generating = False
        for frame in self.frames:
            frame.set_generating_state(False)
        self.generation_stopped.emit()

    def _on_frame_delete_requested(self, index: int):
        """Handle frame delete request"""
        self.remove_frame(index)

    def _on_frame_prompt_edit_requested(self, index: int):
        """Handle prompt edit request"""
        self.prompt_edit_requested.emit(index)

    def _on_frame_save_requested(self, index: int):
        """Handle single image save request"""
        frame = self.get_frame(index)
        if not frame or frame.get_stack_count() == 0:
            show_warning(None, "Warning", "No image to save.")
            return

        filepath, _ = QFileDialog.getSaveFileName(
            None, "Save Image",
            f"frame_{index + 1}.png",
            "PNG Files (*.png);;JPEG Files (*.jpg);;All Files (*.*)"
        )

        if filepath:
            if frame.save_current_image(filepath):
                show_info(None, "Success", f"Image saved to:\n{filepath}")
            else:
                show_error(None, "Error", "Failed to save image.")

    def _on_frame_save_all_requested(self, index: int):
        """Handle save all stacked images request"""
        frame = self.get_frame(index)
        if not frame or frame.get_stack_count() == 0:
            show_warning(None, "Warning", "No images to save.")
            return

        directory = QFileDialog.getExistingDirectory(
            None, "Select Save Directory"
        )

        if directory:
            count = frame.save_all_images(directory, f"frame_{index + 1}")
            if count > 0:
                show_info(None, "Success", f"{count} images saved to:\n{directory}")
            else:
                show_warning(None, "Warning", "No images were saved.")

    # === Generation control ===
    def start_generation(self, repeat_count: int = 1):
        """Start sequential generation for all active frames"""
        active_frames = self.get_active_frames()
        if not active_frames:
            show_warning(None, "Warning", "No frames with prompts to generate.")
            return

        self.repeat_count = repeat_count
        self.current_event_index = 0
        self.total_events = len(active_frames)

        # Build generation queue
        self.generation_queue = []
        for frame in active_frames:
            for r in range(repeat_count):
                self.generation_queue.append((frame.index, r))

        # Lock all frames at start (also emits generation_started)
        self._lock_all_frames()

        print(f"Generation started: {len(self.generation_queue)} total images")

        # Process first item
        self._process_next_generation()

    def stop_generation(self):
        """Stop ongoing generation"""
        self.generation_queue.clear()
        self._unlock_all_frames()  # Also emits generation_stopped
        print("Generation stopped by user")

    def _process_next_generation(self):
        """Process next item in generation queue"""
        if not self.is_generating or not self.generation_queue:
            self._unlock_all_frames()  # Also emits generation_stopped
            print("Generation completed")
            return

        frame_index, repeat_index = self.generation_queue.pop(0)
        frame = self.get_frame(frame_index)

        if frame:
            frame.set_generating_state(True)
            current = (self.total_events * self.repeat_count) - len(self.generation_queue)
            total = self.total_events * self.repeat_count
            self.generation_progress.emit(current, total)

            print(f"Generating frame #{frame_index + 1} (repeat {repeat_index + 1}/{self.repeat_count})")

            # Actual generation will be triggered by StudioTab
            self.frame_updated.emit(frame_index)

    def on_generation_completed(self, frame_index: int, pixmap: QPixmap, pil_image: Image.Image = None):
        """Called when a single generation completes"""
        frame = self.get_frame(frame_index)
        if frame:
            frame.add_image(pixmap, pil_image)

        # Continue with next generation or unlock all frames
        if self.is_generating and self.generation_queue:
            self._process_next_generation()
        else:
            # Single generation or queue completed - unlock all (also emits generation_stopped)
            self._unlock_all_frames()

    def on_generation_failed(self, frame_index: int, error: str):
        """Called when generation fails"""
        print(f"Generation failed for frame #{frame_index + 1}: {error}")

        # Continue with next generation or unlock all frames
        if self.is_generating and self.generation_queue:
            self._process_next_generation()
        else:
            # Single generation or queue completed - unlock all (also emits generation_stopped)
            self._unlock_all_frames()

    # === View save/load ===
    def save_current_view(self, directory: str = None) -> bool:
        """Save current active images from visible frames to timestamped folder

        In wildcard mode, only saves images from currently visible frames.
        """
        if not directory:
            directory = QFileDialog.getExistingDirectory(
                None, "Select Directory for Saving Images"
            )

        if not directory:
            return False

        # Create timestamped subfolder
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # Add mode info to folder name if in wildcard mode
        if self.wildcard_mode_state.is_wildcard_mode:
            page_num = self.wildcard_mode_state.current_page + 1
            save_folder = os.path.join(directory, f"studio_export_{timestamp}_page{page_num}")
        else:
            save_folder = os.path.join(directory, f"studio_export_{timestamp}")

        try:
            os.makedirs(save_folder, exist_ok=True)

            saved_count = 0
            for frame in self.frames:
                # Skip hidden frames (in wildcard mode, only visible frames are saved)
                if frame.isHidden():
                    continue

                if frame.get_stack_count() > 0:
                    # Save current active image (not all stacked images)
                    filepath = os.path.join(save_folder, f"frame_{frame.index + 1}.png")
                    if frame.save_current_image(filepath):
                        saved_count += 1

            if saved_count > 0:
                show_info(None, "Success", f"{saved_count} images saved to:\n{save_folder}")
                return True
            else:
                show_warning(None, "Warning", "No images to save.")
                return False

        except Exception as e:
            print(f"Error saving images: {e}")
            show_error(None, "Error", f"Failed to save images:\n{str(e)}")
            return False

    def save_view_config(self, filepath: str = None) -> bool:
        """Save current view configuration to JSON (original functionality)"""
        if not filepath:
            filepath, _ = QFileDialog.getSaveFileName(
                None, "Save View Config",
                f"studio_view_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                "JSON Files (*.json)"
            )

        if not filepath:
            return False

        try:
            view_data = {
                "version": "1.0",
                "created_at": datetime.now().isoformat(),
                "grid_config": {
                    "rows": self.grid_rows,
                    "cols": self.grid_cols
                },
                "frames": []
            }

            for frame in self.frames:
                frame_data = {
                    "index": frame.index,
                    "prompt_data": frame.get_prompt_data(),
                    "image_count": frame.get_stack_count()
                }
                view_data["frames"].append(frame_data)

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(view_data, f, indent=2, ensure_ascii=False)

            print(f"View saved to: {filepath}")
            return True

        except Exception as e:
            print(f"Error saving view: {e}")
            show_error(None, "Error", f"Failed to save view:\n{str(e)}")
            return False

    def load_view(self, filepath: str = None) -> bool:
        """Load view configuration from JSON"""
        if not filepath:
            filepath, _ = QFileDialog.getOpenFileName(
                None, "Load View",
                "",
                "JSON Files (*.json)"
            )

        if not filepath or not os.path.exists(filepath):
            return False

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                view_data = json.load(f)

            # Load frame prompts
            frames_data = view_data.get("frames", [])
            for frame_data in frames_data:
                index = frame_data.get("index", 0)
                if 0 <= index < len(self.frames):
                    prompt_data = frame_data.get("prompt_data", {})
                    self.frames[index].set_prompt_data(prompt_data)
                    # Also set resolution if present
                    if "resolution" in prompt_data:
                        self.frames[index].set_resolution(prompt_data["resolution"])

            print(f"View loaded from: {filepath}")
            return True

        except Exception as e:
            print(f"Error loading view: {e}")
            show_error(None, "Error", f"Failed to load view:\n{str(e)}")
            return False

    def reset_all_frames(self):
        """Reset all frames to initial state"""
        for frame in self.frames:
            frame.reset()
        print("All frames reset")

    def get_generation_state(self) -> dict:
        """Get current generation state for UI updates"""
        return {
            "is_generating": self.is_generating,
            "current": (self.total_events * self.repeat_count) - len(self.generation_queue) if self.is_generating else 0,
            "total": self.total_events * self.repeat_count if self.is_generating else 0,
            "queue_size": len(self.generation_queue)
        }

    # === Seed fixing ===
    def set_fix_seed_mode(self, enabled: bool):
        """Enable or disable fix seed mode"""
        self.fix_seed_mode = enabled
        print(f"Studio Manager: Fix seed mode {'enabled' if enabled else 'disabled'}")

    def get_last_seed(self) -> Optional[int]:
        """Get the last generated seed"""
        return self.last_generated_seed

    def set_last_seed(self, seed: int):
        """Store the last generated seed"""
        self.last_generated_seed = seed
        print(f"Studio Manager: Last seed updated to {seed}")

    # === Wildcard mode ===
    def enter_wildcard_mode(
        self,
        prompt_pattern: str,
        wc1_name: str,
        wc2_name: str,
        wc1_items: list = None,
        wc2_items: list = None
    ) -> bool:
        """Enter wildcard navigation mode with swappable axes

        Args:
            prompt_pattern: Original prompt pattern with wildcards
            wc1_name: First wildcard name (initially Page axis)
            wc2_name: Second wildcard name (initially Frame axis)
            wc1_items: First wildcard items (optional, fetched if not provided)
            wc2_items: Second wildcard items (optional, fetched if not provided)

        Returns:
            True if successfully entered mode
        """
        # Get wildcard manager (always needed for generator)
        wildcard_manager = None
        if self.app_context and hasattr(self.app_context, 'wildcard_manager'):
            wildcard_manager = self.app_context.wildcard_manager

        if not wildcard_manager:
            # Create fallback wildcard manager
            from core.wildcard_manager import WildcardManager
            wildcard_manager = WildcardManager()
            print("Warning: Using fallback WildcardManager")

        try:
            # Create generator (always needed for combination generation)
            generator = WildcardCombinationGenerator(wildcard_manager)

            # Get items if not provided
            if not wc1_items:
                wc1_items = generator.get_wildcard_items(wc1_name)
            if not wc2_items:
                wc2_items = generator.get_wildcard_items(wc2_name)

            if not wc1_items or not wc2_items:
                print(f"Error: Cannot get items for wildcards {wc1_name}, {wc2_name}")
                return False

            # Create wildcard info
            wc1 = WildcardAxisInfo(
                name=wc1_name,
                items=wc1_items,
                item_count=len(wc1_items)
            )
            wc2 = WildcardAxisInfo(
                name=wc2_name,
                items=wc2_items,
                item_count=len(wc2_items)
            )

            # Generate all combinations
            combination_grid = generator.generate_all_combinations(
                prompt_pattern,
                wc1_name,
                wc2_name
            )

            # Update state
            self.wildcard_mode_state.is_wildcard_mode = True
            self.wildcard_mode_state.original_prompt_pattern = prompt_pattern
            self.wildcard_mode_state.wc1 = wc1
            self.wildcard_mode_state.wc2 = wc2
            self.wildcard_mode_state.axes_swapped = False  # WC1 is Page, WC2 is Frame
            self.wildcard_mode_state.current_page = 0
            self.wildcard_mode_state.combination_grid = combination_grid

            # Apply first page to frames
            self.refresh_current_wildcard_page()

            print(f"Entered wildcard mode: {wc1_name} (Page) x {wc2_name} (Frame)")
            print(f"  Total combinations: {len(combination_grid)}")
            print(f"  Pages: {wc1.item_count}")

            return True

        except Exception as e:
            print(f"Error entering wildcard mode: {e}")
            import traceback
            traceback.print_exc()
            return False

    def exit_wildcard_mode(self):
        """Exit wildcard mode and reset to normal"""
        self.wildcard_mode_state.reset()

        # Show all frames and restore delete buttons
        for frame in self.frames:
            frame.show()
            if hasattr(frame, 'delete_btn'):
                frame.delete_btn.show()

        print("Exited wildcard mode (all frames restored)")

    def navigate_wildcard_page(self, delta: int):
        """Navigate to different page in wildcard mode

        Args:
            delta: Page offset (-1=previous, +1=next)
        """
        if not self.wildcard_mode_state.is_wildcard_mode:
            return

        old_page = self.wildcard_mode_state.current_page
        self.wildcard_mode_state.navigate_page(delta)
        self.refresh_current_wildcard_page()

        new_page = self.wildcard_mode_state.current_page
        current_item = self.wildcard_mode_state.get_current_page_item()
        print(f"Navigated to page {new_page + 1}/{self.wildcard_mode_state.get_total_pages()} (item: {current_item})")

    def swap_wildcard_axes(self):
        """Swap page and frame axes"""
        if not self.wildcard_mode_state.is_wildcard_mode:
            return

        self.wildcard_mode_state.swap_axes()
        self.refresh_current_wildcard_page()

        page_axis = self.wildcard_mode_state.get_page_axis_name()
        frame_axis = self.wildcard_mode_state.get_frame_axis_name()
        print(f"Axes swapped: Page={page_axis}, Frame={frame_axis}")

    def refresh_current_wildcard_page(self):
        """Apply current page's combinations to frames"""
        if not self.wildcard_mode_state.is_wildcard_mode:
            return

        # Get visible combinations
        combinations = self.wildcard_mode_state.get_visible_combinations()

        # Apply to frames
        for i, (x_idx, y_idx, prompt) in enumerate(combinations):
            if i < len(self.frames):
                frame = self.frames[i]
                current_data = frame.get_prompt_data()
                current_data['prompt'] = prompt
                frame.set_prompt_data(current_data)

                # Show frame and hide delete button
                frame.show()
                if hasattr(frame, 'delete_btn'):
                    frame.delete_btn.hide()
            else:
                # Need more frames
                break

        # Hide remaining frames (no prompt assigned)
        for i in range(len(combinations), len(self.frames)):
            frame = self.frames[i]
            current_data = frame.get_prompt_data()
            current_data['prompt'] = ""
            frame.set_prompt_data(current_data)

            # Hide frame with no prompt
            frame.hide()

        print(f"Refreshed {len(combinations)} frame prompts for current page (showing {len(combinations)} frames)")

    def is_in_wildcard_mode(self) -> bool:
        """Check if currently in wildcard mode"""
        return self.wildcard_mode_state.is_wildcard_mode
