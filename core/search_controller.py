import os
import pandas as pd
from multiprocessing import Pool, cpu_count
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from core.search_engine import SearchEngine
from core.search_result_model import SearchResultModel

class SearchWorker(QObject):
    """실제 검색 작업을 수행하는 백그라운드 워커"""
    # [수정] 진행률 시그널이 (완료된 수, 전체 수)를 전달하도록 변경
    progress_updated = pyqtSignal(int, int)
    # [신규] 부분 검색 결과를 전달하는 시그널 추가
    partial_result_ready = pyqtSignal(object)
    # [수정] 검색 완료 시그널은 최종 결과 수만 전달
    search_finished = pyqtSignal(int)
    error_occurred = pyqtSignal(str)

    def __init__(self, search_params: dict, tags_dir: str = 'data/tags', min_file_index: int = None, max_file_index: int = None):
        super().__init__()
        self.search_params = search_params
        self.tags_dir = tags_dir
        self.min_file_index = min_file_index  # None=처음부터, 130=11-09모드
        self.max_file_index = max_file_index  # None=끝까지, 129=24.11모드, 149=25.09모드
        self.is_cancelled = False

    def run_search(self):
        """멀티프로세싱을 사용하여 검색 실행 (imap_unordered로 실시간 처리)"""
        # ... (경로 확인 코드는 그대로) ...

        # 전체 파일 목록 가져오기
        all_files = [f for f in os.listdir(self.tags_dir) if f.endswith('.parquet') and f.startswith('tags_')]

        # min_file_index와 max_file_index에 따라 파일 필터링
        if self.min_file_index is not None or self.max_file_index is not None:
            filtered_files = []
            min_idx = self.min_file_index if self.min_file_index is not None else 0
            max_idx = self.max_file_index if self.max_file_index is not None else 999

            for f in all_files:
                try:
                    # 파일명에서 인덱스 추출 (tags_00.parquet -> 0)
                    file_index = int(f.split('_')[1].split('.')[0])
                    if min_idx <= file_index <= max_idx:
                        filtered_files.append(f)
                except (IndexError, ValueError):
                    # 파일명 형식이 맞지 않으면 건너뜀
                    continue

            files_to_search = [os.path.join(self.tags_dir, f) for f in filtered_files]

            # 검색 범위 로그 출력
            if self.min_file_index is not None and self.max_file_index is not None:
                print(f"🔍 검색 범위 제한: tags_{min_idx:02d} ~ tags_{max_idx:02d} ({len(files_to_search)}개 파일)")
            elif self.max_file_index is not None:
                print(f"🔍 검색 범위 제한: tags_00 ~ tags_{max_idx:02d} ({len(files_to_search)}개 파일)")
            else:
                print(f"🔍 검색 범위 제한: tags_{min_idx:02d} ~ 끝 ({len(files_to_search)}개 파일)")
        else:
            files_to_search = [os.path.join(self.tags_dir, f) for f in all_files]
            print(f"🔍 전체 범위 검색: {len(files_to_search)}개 파일")

        if not files_to_search:
            self.error_occurred.emit("검색할 .parquet 파일이 없습니다.")
            return

        engine = SearchEngine()
        process_args = [(file, self.search_params) for file in files_to_search]
        total_files = len(files_to_search)
        completed_count = 0
        total_rows = 0

        try:
            num_processes = min(cpu_count() // 2, 8)
            if num_processes == 0: num_processes = 1

            with Pool(processes=num_processes) as pool:
                # [수정] imap_unordered를 사용하여 결과가 나오는 즉시 처리
                results_iterator = pool.starmap(engine.search_in_file, process_args)
                
                for df_result in results_iterator:
                    if self.is_cancelled:
                        pool.terminate()
                        break
                    
                    completed_count += 1
                    if df_result is not None and not df_result.empty:
                        total_rows += len(df_result)
                        self.partial_result_ready.emit(df_result)
                    
                    self.progress_updated.emit(completed_count, total_files)

            if self.is_cancelled:
                self.search_finished.emit(0)
                return
            
            self.search_finished.emit(total_rows)

        except Exception as e:
            self.error_occurred.emit(f"검색 중 오류 발생: {e}")

    def cancel(self):
        self.is_cancelled = True


class SearchController(QObject):
    """UI와 SearchEngine을 중재하고 비동기 검색을 관리"""
    # [수정] 시그널 이름 및 타입 변경
    search_progress = pyqtSignal(int, int)
    partial_search_result = pyqtSignal(object)
    search_complete = pyqtSignal(int)
    search_error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.worker_thread = None
        self.worker = None
        self.min_file_index = None  # 검색 시작 인덱스 (None=0, 130=11-09모드)
        self.max_file_index = None  # 검색 종료 인덱스 (None=끝까지, 129=24.11모드, 149=25.09모드)

    def set_file_range(self, min_index: int = None, max_index: int = None):
        """
        검색 파일 범위를 설정합니다.

        Args:
            min_index: 최소 파일 인덱스 (None=0부터, 130=11-09모드)
            max_index: 최대 파일 인덱스 (None=끝까지, 129=24.11모드, 149=25.09모드)
        """
        self.min_file_index = min_index
        self.max_file_index = max_index

        # 로그 출력
        if min_index is None and max_index is None:
            print(f"🔍 검색 모드: 전체 범위 (tags_00 ~ tags_149)")
        elif min_index is not None and max_index is not None:
            file_count = max_index - min_index + 1
            print(f"🔍 검색 모드: 범위 제한 (tags_{min_index:02d} ~ tags_{max_index:02d}, {file_count}개 파일)")
        elif max_index is not None:
            file_count = max_index + 1
            print(f"🔍 검색 모드: 범위 제한 (tags_00 ~ tags_{max_index:02d}, {file_count}개 파일)")
        else:
            print(f"🔍 검색 모드: 범위 제한 (tags_{min_index:02d} ~ 끝)")

    def set_max_file_index(self, max_index: int = None):
        """
        검색 파일 최대 인덱스만 설정합니다. (하위 호환성)

        Args:
            max_index: 최대 파일 인덱스 (None=전체, 129=24.11모드, 149=25.09모드)
        """
        self.set_file_range(None, max_index)

    def start_search(self, search_params: dict):
        # ... (기존 start_search 로직과 거의 동일) ...
        self.worker_thread = QThread()
        self.worker = SearchWorker(search_params, min_file_index=self.min_file_index, max_file_index=self.max_file_index)
        self.worker.moveToThread(self.worker_thread)

        # [수정] 변경된 시그널 연결
        self.worker.progress_updated.connect(self.search_progress)
        self.worker.partial_result_ready.connect(self.partial_search_result)
        self.worker.search_finished.connect(self.on_search_finished)
        self.worker.error_occurred.connect(self.search_error)
        
        self.worker_thread.started.connect(self.worker.run_search)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.start()

    def cancel_search(self):
        """진행 중인 검색을 취소"""
        if self.worker:
            self.worker.cancel()
        if self.worker_thread:
            self.worker_thread.quit()
            self.worker_thread.wait()

    def on_search_finished(self, total_count: int):
        """검색 완료 시 스레드를 정리하고 완료 시그널 전달"""
        self.search_complete.emit(total_count)
        if self.worker_thread:
            self.worker_thread.quit()