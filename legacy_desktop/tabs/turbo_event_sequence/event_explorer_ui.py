"""
이벤트 탐색기 UI (Event Explorer UI)

NAIA_event_dataset.parquet 파일을 분석하기 위한 tkinter 기반 UI

특징:
1. Parent/Children 이벤트 관계 탐색
2. 검색 및 필터링
3. 서브 이벤트 분석
4. 태그 통계
5. Variant Set 필터링
6. Parent-Child 태그 차이 분석

사용법:
    python event_explorer_ui.py
"""

import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, List, Set, Optional, Tuple
from collections import Counter, OrderedDict
import pandas as pd

script_dir = os.path.dirname(os.path.abspath(__file__))

# 이벤트 데이터 경로
EVENT_PARQUET_PATH = os.path.join(script_dir, 'continue_events', 'NAIA_event_dataset_v4.parquet')


class EventExplorerUI:
    """이벤트 탐색기 UI"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Event Explorer - NAIA Event Dataset")
        self.root.geometry("1500x950")

        # 데이터
        self.event_df: Optional[pd.DataFrame] = None
        self.parent_df: Optional[pd.DataFrame] = None
        self.current_parent_id: Optional[int] = None
        self.children_df: Optional[pd.DataFrame] = None

        # 검색 결과
        self.filtered_parents: Optional[pd.DataFrame] = None

        self.setup_ui()
        self.load_data()

    def setup_ui(self):
        """UI 구성"""
        # 메인 프레임
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 상단: 데이터 정보 및 검색
        top_frame = ttk.LabelFrame(main_frame, text="Data Info & Search", padding="10")
        top_frame.pack(fill=tk.X, pady=(0, 10))

        # 데이터 정보 라벨
        self.info_label = ttk.Label(top_frame, text="Loading...", font=('', 10))
        self.info_label.pack(anchor=tk.W)

        # 검색 프레임
        search_frame = ttk.Frame(top_frame)
        search_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Label(search_frame, text="Search (general tags):").pack(side=tk.LEFT)
        self.search_entry = ttk.Entry(search_frame, width=40)
        self.search_entry.pack(side=tk.LEFT, padx=(5, 10))
        self.search_entry.bind('<Return>', lambda e: self.search_parents())

        ttk.Label(search_frame, text="Exclude:").pack(side=tk.LEFT)
        self.exclude_entry = ttk.Entry(search_frame, width=25)
        self.exclude_entry.pack(side=tk.LEFT, padx=(5, 10))

        ttk.Button(search_frame, text="Search", command=self.search_parents).pack(side=tk.LEFT, padx=5)
        ttk.Button(search_frame, text="Reset", command=self.reset_search).pack(side=tk.LEFT)

        # 필터 프레임 (페이지 수 + Variant Set)
        filter_frame = ttk.Frame(top_frame)
        filter_frame.pack(fill=tk.X, pady=(5, 0))

        # 페이지 수 필터
        self.page_filter_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(filter_frame, text="Filter by page count:", variable=self.page_filter_var).pack(side=tk.LEFT)

        ttk.Label(filter_frame, text="Min:").pack(side=tk.LEFT, padx=(10, 2))
        self.min_pages_entry = ttk.Entry(filter_frame, width=5)
        self.min_pages_entry.insert(0, "2")
        self.min_pages_entry.pack(side=tk.LEFT)

        ttk.Label(filter_frame, text="Max:").pack(side=tk.LEFT, padx=(10, 2))
        self.max_pages_entry = ttk.Entry(filter_frame, width=5)
        self.max_pages_entry.insert(0, "100")
        self.max_pages_entry.pack(side=tk.LEFT)

        # Variant Set 필터
        ttk.Separator(filter_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=15, fill=tk.Y)

        ttk.Label(filter_frame, text="Variant Set:", font=('', 9, 'bold')).pack(side=tk.LEFT)
        self.variant_filter_var = tk.StringVar(value="all")
        ttk.Radiobutton(filter_frame, text="All", variable=self.variant_filter_var, value="all").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(filter_frame, text="Variant Set Only", variable=self.variant_filter_var, value="variant").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(filter_frame, text="Non-Variant Only", variable=self.variant_filter_var, value="non_variant").pack(side=tk.LEFT, padx=5)

        # 중간: 좌우 분할
        paned = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # 왼쪽: Parent 이벤트 목록
        left_frame = ttk.LabelFrame(paned, text="Parent Events", padding="5")
        paned.add(left_frame, weight=1)

        # Parent 목록 상단 정보
        self.parent_info_label = ttk.Label(left_frame, text="", font=('', 9))
        self.parent_info_label.pack(anchor=tk.W)

        # Parent 목록 Treeview
        parent_tree_frame = ttk.Frame(left_frame)
        parent_tree_frame.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

        self.parent_tree = ttk.Treeview(
            parent_tree_frame,
            columns=('id', 'rating', 'children', 'variant', 'tags'),
            show='headings',
            height=18
        )
        self.parent_tree.heading('id', text='ID')
        self.parent_tree.heading('rating', text='Rating')
        self.parent_tree.heading('children', text='Children')
        self.parent_tree.heading('variant', text='Variant')
        self.parent_tree.heading('tags', text='General Tags (Preview)')

        self.parent_tree.column('id', width=80)
        self.parent_tree.column('rating', width=50)
        self.parent_tree.column('children', width=55)
        self.parent_tree.column('variant', width=50)
        self.parent_tree.column('tags', width=250)

        parent_scroll = ttk.Scrollbar(parent_tree_frame, orient=tk.VERTICAL, command=self.parent_tree.yview)
        self.parent_tree.configure(yscrollcommand=parent_scroll.set)
        self.parent_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        parent_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.parent_tree.bind('<<TreeviewSelect>>', self.on_parent_select)

        # 오른쪽: Children 이벤트 상세
        right_frame = ttk.LabelFrame(paned, text="Children Events (Sub-events)", padding="5")
        paned.add(right_frame, weight=2)

        # Children 상단 정보
        self.children_info_label = ttk.Label(right_frame, text="Select a parent event", font=('', 9))
        self.children_info_label.pack(anchor=tk.W)

        # Children 목록 Treeview
        children_tree_frame = ttk.Frame(right_frame)
        children_tree_frame.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

        self.children_tree = ttk.Treeview(
            children_tree_frame,
            columns=('idx', 'id', 'rating', 'score', 'tags'),
            show='headings',
            height=12
        )
        self.children_tree.heading('idx', text='#')
        self.children_tree.heading('id', text='ID')
        self.children_tree.heading('rating', text='Rating')
        self.children_tree.heading('score', text='Score')
        self.children_tree.heading('tags', text='General Tags')

        self.children_tree.column('idx', width=35)
        self.children_tree.column('id', width=80)
        self.children_tree.column('rating', width=50)
        self.children_tree.column('score', width=50)
        self.children_tree.column('tags', width=450)

        children_scroll = ttk.Scrollbar(children_tree_frame, orient=tk.VERTICAL, command=self.children_tree.yview)
        self.children_tree.configure(yscrollcommand=children_scroll.set)
        self.children_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        children_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.children_tree.bind('<<TreeviewSelect>>', self.on_child_select)

        # 하단: 선택된 이벤트 상세 정보
        detail_frame = ttk.LabelFrame(main_frame, text="Selected Event Details", padding="10")
        detail_frame.pack(fill=tk.X, pady=(10, 0))

        self.detail_text = tk.Text(detail_frame, height=8, wrap=tk.WORD, font=('Consolas', 9))
        detail_scroll = ttk.Scrollbar(detail_frame, orient=tk.VERTICAL, command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=detail_scroll.set)
        self.detail_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        detail_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 하단 버튼
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(button_frame, text="Analyze Tag Distribution", command=self.analyze_tags).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Analyze Tag Diff (Chain)", command=self.analyze_tag_diff_chain).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Export Current Selection", command=self.export_selection).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Refresh", command=self.refresh_parent_list).pack(side=tk.RIGHT, padx=5)

    def load_data(self):
        """데이터 로드"""
        if not os.path.exists(EVENT_PARQUET_PATH):
            messagebox.showerror("Error", f"File not found:\n{EVENT_PARQUET_PATH}")
            self.info_label.config(text="Error: File not found")
            return

        try:
            self.event_df = pd.read_parquet(EVENT_PARQUET_PATH)
            self.parent_df = self.event_df[self.event_df["has_children"] == True].copy()

            # Children 카운트 계산
            children_counts = self.event_df.groupby('parent_id').size()
            self.parent_df['children_count'] = self.parent_df['id'].map(children_counts).fillna(0).astype(int)

            # Variant Set 여부 계산
            self.parent_df['is_variant_set'] = self.parent_df['meta'].str.contains('variant set', case=False, na=False)

            # 전체 통계
            total_events = len(self.event_df)
            total_parents = len(self.parent_df)
            total_children = total_events - total_parents
            variant_count = self.parent_df['is_variant_set'].sum()
            non_variant_count = total_parents - variant_count

            self.info_label.config(
                text=f"Total: {total_events:,} | Parents: {total_parents:,} | Children: {total_children:,} | "
                     f"Variant Sets: {variant_count:,} | Non-Variant: {non_variant_count:,}"
            )

            self.filtered_parents = self.parent_df.copy()
            self.refresh_parent_list()

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load data:\n{str(e)}")
            self.info_label.config(text=f"Error: {str(e)}")

    def search_parents(self):
        """Parent 이벤트 검색"""
        if self.parent_df is None:
            return

        search_text = self.search_entry.get().strip()
        exclude_text = self.exclude_entry.get().strip()

        result = self.parent_df.copy()

        # 검색어 필터
        if search_text:
            search_terms = [t.strip() for t in search_text.split(',') if t.strip()]
            for term in search_terms:
                mask = result['general'].str.contains(term, case=False, na=False)
                result = result[mask]

        # 제외어 필터
        if exclude_text:
            exclude_terms = [t.strip() for t in exclude_text.split(',') if t.strip()]
            for term in exclude_terms:
                mask = ~result['general'].str.contains(term, case=False, na=False)
                result = result[mask]

        # 페이지 수 필터
        if self.page_filter_var.get():
            try:
                min_pages = int(self.min_pages_entry.get())
                max_pages = int(self.max_pages_entry.get())
                result = result[(result['children_count'] >= min_pages) & (result['children_count'] <= max_pages)]
            except ValueError:
                pass

        # Variant Set 필터
        variant_filter = self.variant_filter_var.get()
        if variant_filter == "variant":
            result = result[result['is_variant_set'] == True]
        elif variant_filter == "non_variant":
            result = result[result['is_variant_set'] == False]

        self.filtered_parents = result
        self.refresh_parent_list()

    def reset_search(self):
        """검색 초기화"""
        self.search_entry.delete(0, tk.END)
        self.exclude_entry.delete(0, tk.END)
        self.page_filter_var.set(False)
        self.variant_filter_var.set("all")
        self.filtered_parents = self.parent_df.copy() if self.parent_df is not None else None
        self.refresh_parent_list()

    def refresh_parent_list(self):
        """Parent 목록 새로고침"""
        # 기존 항목 삭제
        for item in self.parent_tree.get_children():
            self.parent_tree.delete(item)

        if self.filtered_parents is None or len(self.filtered_parents) == 0:
            self.parent_info_label.config(text="No results")
            return

        self.parent_info_label.config(text=f"Showing {len(self.filtered_parents):,} parents")

        # 최대 500개만 표시 (성능)
        display_df = self.filtered_parents.head(500)

        for _, row in display_df.iterrows():
            tags_preview = str(row.get('general', ''))[:70] + '...' if len(str(row.get('general', ''))) > 70 else str(row.get('general', ''))
            variant_mark = "Yes" if row.get('is_variant_set', False) else ""
            self.parent_tree.insert('', tk.END, values=(
                row['id'],
                row.get('rating', ''),
                row.get('children_count', 0),
                variant_mark,
                tags_preview
            ))

        if len(self.filtered_parents) > 500:
            self.parent_info_label.config(
                text=f"Showing 500 of {len(self.filtered_parents):,} parents (use search to narrow down)"
            )

    def on_parent_select(self, event):
        """Parent 선택 시"""
        selection = self.parent_tree.selection()
        if not selection:
            return

        item = self.parent_tree.item(selection[0])
        parent_id = item['values'][0]
        self.current_parent_id = parent_id
        self.load_children(parent_id)

    def load_children(self, parent_id: int):
        """선택된 Parent의 Children 로드"""
        if self.event_df is None:
            return

        self.children_df = self.event_df[self.event_df['parent_id'] == parent_id].copy()

        # ID 기준 정렬 (시퀀스 순서)
        self.children_df = self.children_df.sort_values('id').reset_index(drop=True)

        # Children 목록 새로고침
        for item in self.children_tree.get_children():
            self.children_tree.delete(item)

        # Parent의 variant set 여부 확인
        parent_row = self.parent_df[self.parent_df['id'] == parent_id]
        is_variant = parent_row.iloc[0].get('is_variant_set', False) if len(parent_row) > 0 else False
        variant_info = " [Variant Set]" if is_variant else ""

        self.children_info_label.config(text=f"Parent ID: {parent_id}{variant_info} | Children: {len(self.children_df):,}")

        for idx, (_, row) in enumerate(self.children_df.iterrows()):
            tags = str(row.get('general', ''))
            self.children_tree.insert('', tk.END, values=(
                idx + 1,  # 1-based index
                row['id'],
                row.get('rating', ''),
                row.get('score', 0),
                tags
            ))

        # Parent 상세 정보도 표시
        if len(parent_row) > 0:
            self.show_event_detail(parent_row.iloc[0], is_parent=True)

    def on_child_select(self, event):
        """Child 선택 시"""
        selection = self.children_tree.selection()
        if not selection or self.children_df is None:
            return

        item = self.children_tree.item(selection[0])
        child_id = item['values'][1]  # idx=0, id=1

        child_row = self.children_df[self.children_df['id'] == child_id]
        if len(child_row) > 0:
            self.show_event_detail(child_row.iloc[0], is_parent=False)

    def show_event_detail(self, row: pd.Series, is_parent: bool = False):
        """이벤트 상세 정보 표시"""
        self.detail_text.delete('1.0', tk.END)

        event_type = "PARENT" if is_parent else "CHILD"
        text = f"=== {event_type} EVENT ===\n"
        text += f"ID: {row['id']}\n"
        text += f"Parent ID: {row.get('parent_id', 'N/A')}\n"
        text += f"Rating: {row.get('rating', 'N/A')}\n"
        text += f"Score: {row.get('score', 'N/A')}\n"
        text += f"Has Children: {row.get('has_children', False)}\n"

        # Meta 태그 (Variant Set 포함 여부 강조)
        meta = str(row.get('meta', ''))
        if 'variant set' in meta.lower():
            text += f"Meta: {meta} [VARIANT SET]\n"
        else:
            text += f"Meta: {meta}\n"

        text += f"\n--- General Tags ---\n"
        text += f"{row.get('general', '')}\n"

        # 추가 컬럼 표시
        skip_cols = {'id', 'parent_id', 'rating', 'score', 'has_children', 'general', 'children_count', 'is_variant_set', 'meta'}
        other_cols = [c for c in row.index if c not in skip_cols]
        if other_cols:
            text += f"\n--- Other Columns ---\n"
            for col in other_cols:
                val = row.get(col, '')
                if pd.notna(val) and str(val).strip():
                    text += f"{col}: {val}\n"

        self.detail_text.insert('1.0', text)

    def analyze_tags(self):
        """현재 선택된 Children의 태그 분포 분석"""
        if self.children_df is None or len(self.children_df) == 0:
            messagebox.showinfo("Info", "No children selected. Select a parent first.")
            return

        # 태그 카운트
        tag_counter = Counter()
        for _, row in self.children_df.iterrows():
            general = str(row.get('general', ''))
            tags = [t.strip() for t in general.split(',') if t.strip()]
            tag_counter.update(tags)

        # 결과 창
        result_window = tk.Toplevel(self.root)
        result_window.title(f"Tag Analysis - Parent {self.current_parent_id}")
        result_window.geometry("600x500")

        ttk.Label(
            result_window,
            text=f"Tag distribution across {len(self.children_df)} children events",
            font=('', 10, 'bold')
        ).pack(pady=10)

        # Treeview
        tree_frame = ttk.Frame(result_window)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        tree = ttk.Treeview(tree_frame, columns=('tag', 'count', 'percent'), show='headings')
        tree.heading('tag', text='Tag')
        tree.heading('count', text='Count')
        tree.heading('percent', text='%')

        tree.column('tag', width=350)
        tree.column('count', width=80)
        tree.column('percent', width=80)

        scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        total_children = len(self.children_df)
        for tag, count in tag_counter.most_common(100):
            percent = (count / total_children) * 100
            tree.insert('', tk.END, values=(tag, count, f"{percent:.1f}%"))

    def analyze_tag_diff_chain(self):
        """Parent → Child 체인에서 태그 차이 분석"""
        if self.children_df is None or len(self.children_df) == 0:
            messagebox.showinfo("Info", "No children selected. Select a parent first.")
            return

        if self.parent_df is None or self.current_parent_id is None:
            return

        # Parent 태그 가져오기
        parent_row = self.parent_df[self.parent_df['id'] == self.current_parent_id]
        if len(parent_row) == 0:
            return

        parent_tags = set(t.strip() for t in str(parent_row.iloc[0].get('general', '')).split(',') if t.strip())

        # 결과 창
        result_window = tk.Toplevel(self.root)
        result_window.title(f"Tag Diff Analysis - Parent {self.current_parent_id}")
        result_window.geometry("900x700")

        # 상단 정보
        info_frame = ttk.Frame(result_window, padding="10")
        info_frame.pack(fill=tk.X)

        ttk.Label(
            info_frame,
            text=f"Parent → Children Tag Difference Analysis ({len(self.children_df)} children)",
            font=('', 11, 'bold')
        ).pack(anchor=tk.W)

        ttk.Label(
            info_frame,
            text=f"Parent tags: {len(parent_tags)} tags",
            font=('', 9)
        ).pack(anchor=tk.W)

        # 탭 노트북
        notebook = ttk.Notebook(result_window)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # 탭 1: 순차 비교 (Parent → Child1 → Child2 → ...)
        chain_frame = ttk.Frame(notebook)
        notebook.add(chain_frame, text="Sequential Diff (Chain)")

        chain_tree = ttk.Treeview(
            chain_frame,
            columns=('step', 'id', 'added', 'removed', 'kept'),
            show='headings'
        )
        chain_tree.heading('step', text='Step')
        chain_tree.heading('id', text='Event ID')
        chain_tree.heading('added', text='Added Tags')
        chain_tree.heading('removed', text='Removed Tags')
        chain_tree.heading('kept', text='Kept')

        chain_tree.column('step', width=50)
        chain_tree.column('id', width=80)
        chain_tree.column('added', width=300)
        chain_tree.column('removed', width=300)
        chain_tree.column('kept', width=50)

        chain_scroll = ttk.Scrollbar(chain_frame, orient=tk.VERTICAL, command=chain_tree.yview)
        chain_tree.configure(yscrollcommand=chain_scroll.set)
        chain_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        chain_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 순차 비교 데이터 생성
        prev_tags = parent_tags
        chain_tree.insert('', tk.END, values=(
            "Parent",
            self.current_parent_id,
            f"[Base: {len(parent_tags)} tags]",
            "",
            len(parent_tags)
        ))

        for idx, (_, row) in enumerate(self.children_df.iterrows()):
            current_tags = set(t.strip() for t in str(row.get('general', '')).split(',') if t.strip())

            added = current_tags - prev_tags
            removed = prev_tags - current_tags
            kept = len(current_tags & prev_tags)

            added_str = ', '.join(sorted(added)[:5])
            if len(added) > 5:
                added_str += f" ... (+{len(added)-5} more)"

            removed_str = ', '.join(sorted(removed)[:5])
            if len(removed) > 5:
                removed_str += f" ... (+{len(removed)-5} more)"

            chain_tree.insert('', tk.END, values=(
                f"Child {idx+1}",
                row['id'],
                added_str if added else "-",
                removed_str if removed else "-",
                kept
            ))

            prev_tags = current_tags

        # 탭 2: Parent vs All Children (공통/고유)
        compare_frame = ttk.Frame(notebook)
        notebook.add(compare_frame, text="Parent vs Children")

        # 태그 분류
        all_children_tags: Set[str] = set()
        children_tag_counts: Counter = Counter()

        for _, row in self.children_df.iterrows():
            tags = set(t.strip() for t in str(row.get('general', '')).split(',') if t.strip())
            all_children_tags.update(tags)
            children_tag_counts.update(tags)

        common_tags = parent_tags & all_children_tags
        parent_only = parent_tags - all_children_tags
        children_only = all_children_tags - parent_tags

        # 3열 레이아웃
        columns_frame = ttk.Frame(compare_frame)
        columns_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 왼쪽: Parent Only
        left_col = ttk.LabelFrame(columns_frame, text=f"Parent Only ({len(parent_only)})")
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)

        parent_only_list = tk.Listbox(left_col, font=('Consolas', 9))
        parent_only_scroll = ttk.Scrollbar(left_col, orient=tk.VERTICAL, command=parent_only_list.yview)
        parent_only_list.configure(yscrollcommand=parent_only_scroll.set)
        parent_only_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        parent_only_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        for tag in sorted(parent_only):
            parent_only_list.insert(tk.END, tag)

        # 중앙: Common
        mid_col = ttk.LabelFrame(columns_frame, text=f"Common ({len(common_tags)})")
        mid_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)

        common_list = tk.Listbox(mid_col, font=('Consolas', 9))
        common_scroll = ttk.Scrollbar(mid_col, orient=tk.VERTICAL, command=common_list.yview)
        common_list.configure(yscrollcommand=common_scroll.set)
        common_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        common_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        for tag in sorted(common_tags):
            count = children_tag_counts.get(tag, 0)
            common_list.insert(tk.END, f"{tag} ({count}/{len(self.children_df)})")

        # 오른쪽: Children Only
        right_col = ttk.LabelFrame(columns_frame, text=f"Children Only ({len(children_only)})")
        right_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)

        children_only_list = tk.Listbox(right_col, font=('Consolas', 9))
        children_only_scroll = ttk.Scrollbar(right_col, orient=tk.VERTICAL, command=children_only_list.yview)
        children_only_list.configure(yscrollcommand=children_only_scroll.set)
        children_only_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        children_only_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 빈도순 정렬
        children_only_sorted = sorted(children_only, key=lambda t: -children_tag_counts.get(t, 0))
        for tag in children_only_sorted:
            count = children_tag_counts.get(tag, 0)
            children_only_list.insert(tk.END, f"{tag} ({count})")

        # 탭 3: 변화 패턴 요약
        summary_frame = ttk.Frame(notebook)
        notebook.add(summary_frame, text="Summary")

        summary_text = tk.Text(summary_frame, font=('Consolas', 10), wrap=tk.WORD)
        summary_scroll = ttk.Scrollbar(summary_frame, orient=tk.VERTICAL, command=summary_text.yview)
        summary_text.configure(yscrollcommand=summary_scroll.set)
        summary_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        summary_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 요약 텍스트 생성
        summary = f"""=== Tag Difference Summary ===

Parent ID: {self.current_parent_id}
Children Count: {len(self.children_df)}

--- Tag Counts ---
Parent Tags: {len(parent_tags)}
All Children Tags (Union): {len(all_children_tags)}
Common Tags: {len(common_tags)}
Parent Only: {len(parent_only)}
Children Only: {len(children_only)}

--- Consistency Analysis ---
Tags in ALL children: {sum(1 for t, c in children_tag_counts.items() if c == len(self.children_df))}
Tags in >50% children: {sum(1 for t, c in children_tag_counts.items() if c >= len(self.children_df) / 2)}
Tags in only 1 child: {sum(1 for t, c in children_tag_counts.items() if c == 1)}

--- Parent Only Tags ---
{', '.join(sorted(parent_only)) if parent_only else '(None)'}

--- Most Common Children-Only Tags ---
"""
        # 가장 흔한 Children-only 태그
        for tag in children_only_sorted[:10]:
            count = children_tag_counts.get(tag, 0)
            summary += f"  {tag}: {count}/{len(self.children_df)} ({count/len(self.children_df)*100:.0f}%)\n"

        summary_text.insert('1.0', summary)
        summary_text.config(state=tk.DISABLED)

    def export_selection(self):
        """현재 선택 내보내기"""
        if self.filtered_parents is None or len(self.filtered_parents) == 0:
            messagebox.showinfo("Info", "No data to export")
            return

        output_path = os.path.join(script_dir, 'exported_events.csv')
        try:
            self.filtered_parents.to_csv(output_path, index=False)
            messagebox.showinfo("Success", f"Exported {len(self.filtered_parents)} events to:\n{output_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Export failed:\n{str(e)}")


def main():
    root = tk.Tk()
    app = EventExplorerUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
