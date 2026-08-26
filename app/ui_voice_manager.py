"""Voice Downloader & Manager Module for TTSx Studio.

Scans Hugging Face repositories (official rhasspy/piper-voices and custom user repos),
downloads Piper ONNX models & configs, and manages installed local models.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QProgressBar,
    QMessageBox,
    QFrame,
    QWidget,
    QAbstractItemView,
)

from .runtime_paths import models_path, app_path


@dataclass
class VoiceModelItem:
    voice_id: str
    name: str
    language_code: str
    country_code: str
    language_name: str
    gender: str
    quality: str
    onnx_url: str
    json_url: str
    onnx_size_bytes: int = 0
    is_downloaded: bool = False
    local_onnx_path: str = ""
    local_json_path: str = ""
    repo_source: str = ""


def parse_huggingface_repo_id(url_or_repo: str) -> Tuple[str, str]:
    """Extract (repo_type, repo_id) from a Hugging Face URL or identifier string.
    
    Supports:
      - Models: 'owner/repo' or 'https://huggingface.co/owner/repo'
      - Buckets: 'https://huggingface.co/buckets/owner/repo' or 'buckets/owner/repo'
      - Datasets: 'https://huggingface.co/datasets/owner/repo' or 'datasets/owner/repo'
    """
    clean = url_or_repo.strip().rstrip("/")
    if not clean:
        return "rhasspy", "rhasspy/piper-voices"

    # Match /buckets/owner/repo
    m_bucket = re.search(r"huggingface\.co/buckets/([^/]+/[^/]+)", clean) or re.match(r"^buckets/([^/]+/[^/]+)", clean)
    if m_bucket:
        return "bucket", m_bucket.group(1)

    # Match /datasets/owner/repo
    m_dataset = re.search(r"huggingface\.co/datasets/([^/]+/[^/]+)", clean) or re.match(r"^datasets/([^/]+/[^/]+)", clean)
    if m_dataset:
        return "dataset", m_dataset.group(1)

    # Match standard huggingface.co/owner/repo
    m_model = re.search(r"huggingface\.co/([^/]+/[^/]+)", clean)
    if m_model:
        rid = m_model.group(1)
        if rid.startswith("buckets/"):
            return "bucket", rid[len("buckets/"):]
        if rid.startswith("datasets/"):
            return "dataset", rid[len("datasets/"):]
        return "auto", rid

    parts = clean.split("/")
    if len(parts) == 2:
        return "auto", clean
    elif len(parts) >= 3 and parts[0] in ("buckets", "datasets"):
        return parts[0][:-1] if parts[0].endswith("s") else parts[0], f"{parts[1]}/{parts[2]}"

    return "auto", clean


def format_size(bytes_val: int) -> str:
    if bytes_val <= 0:
        return "N/A"
    mb = bytes_val / (1024 * 1024)
    if mb >= 1024:
        return f"{mb/1024:.2f} GB"
    return f"{mb:.1f} MB"


class VoiceScanWorker(QThread):
    progress_signal = Signal(str)
    finished_signal = Signal(list)
    error_signal = Signal(str)

    def __init__(self, repo_input: str):
        super().__init__()
        self.repo_input = repo_input

    def run(self):
        try:
            repo_type, repo_id = parse_huggingface_repo_id(self.repo_input)
            self.progress_signal.emit(f"Đang kết nối tới Hugging Face ({repo_id})...")

            items: List[VoiceModelItem] = []
            if "rhasspy/piper-voices" in repo_id.lower():
                items = self._fetch_rhasspy_voices(repo_id)
            else:
                items = self._fetch_custom_hf_repo(repo_id, repo_type=repo_type)

            self.finished_signal.emit(items)
        except Exception as e:
            self.error_signal.emit(str(e))

    def _fetch_rhasspy_voices(self, repo_id: str) -> List[VoiceModelItem]:
        self.progress_signal.emit("Đang tải danh mục voices.json từ rhasspy/piper-voices...")
        json_url = f"https://huggingface.co/{repo_id}/raw/main/voices.json"
        req = urllib.request.Request(json_url, headers={"User-Agent": "TTSx-Studio/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        local_piper_dir = Path(models_path("piper"))
        local_piper_en_dir = Path(models_path("piper-en"))
        results: List[VoiceModelItem] = []

        for voice_key, v in data.items():
            lang_info = v.get("language", {})
            lang_code = lang_info.get("code", "")
            country_code = lang_info.get("country_english", "") or lang_info.get("family", "")
            lang_name = lang_info.get("name_native", "") or lang_info.get("name_english", "")
            quality = v.get("quality", "medium")
            name = v.get("name", voice_key)
            gender = v.get("gender", "unknown")

            # Files mapping
            files = v.get("files", {})
            onnx_rel = ""
            json_rel = ""
            onnx_size = 0

            for f_path, f_meta in files.items():
                if f_path.endswith(".onnx"):
                    onnx_rel = f_path
                    onnx_size = f_meta.get("size_bytes", 0)
                elif f_path.endswith(".onnx.json"):
                    json_rel = f_path

            if not onnx_rel:
                continue

            onnx_url = f"https://huggingface.co/{repo_id}/resolve/main/{onnx_rel}"
            json_url = f"https://huggingface.co/{repo_id}/resolve/main/{json_rel}" if json_rel else f"{onnx_url}.json"

            model_filename = os.path.basename(onnx_rel)
            json_filename = f"{model_filename}.json"

            target_dir = local_piper_en_dir if lang_code.startswith("en") else local_piper_dir
            local_onnx = target_dir / model_filename
            local_json = target_dir / json_filename
            is_downloaded = local_onnx.exists() and local_onnx.stat().st_size > 1024

            results.append(
                VoiceModelItem(
                    voice_id=voice_key,
                    name=name,
                    language_code=lang_code,
                    country_code=country_code,
                    language_name=lang_name,
                    gender=gender,
                    quality=quality,
                    onnx_url=onnx_url,
                    json_url=json_url,
                    onnx_size_bytes=onnx_size,
                    is_downloaded=is_downloaded,
                    local_onnx_path=str(local_onnx),
                    local_json_path=str(local_json),
                    repo_source=repo_id,
                )
            )

        return results

    def _fetch_custom_hf_repo(self, repo_id: str, repo_type: str = "auto") -> List[VoiceModelItem]:
        self.progress_signal.emit(f"Đang quét cây thư mục repository {repo_id}...")
        
        endpoints = []
        if repo_type == "bucket":
            endpoints.append(("bucket", f"https://huggingface.co/api/buckets/{repo_id}/tree?recursive=true"))
        elif repo_type == "dataset":
            endpoints.append(("dataset", f"https://huggingface.co/api/datasets/{repo_id}/tree/main?recursive=true"))
        elif repo_type == "model":
            endpoints.append(("model", f"https://huggingface.co/api/models/{repo_id}/tree/main?recursive=true"))
        else:
            endpoints.append(("model", f"https://huggingface.co/api/models/{repo_id}/tree/main?recursive=true"))
            endpoints.append(("bucket", f"https://huggingface.co/api/buckets/{repo_id}/tree?recursive=true"))
            endpoints.append(("dataset", f"https://huggingface.co/api/datasets/{repo_id}/tree/main?recursive=true"))

        tree = None
        resolved_type = "model"
        last_err = None

        for r_type, api_url in endpoints:
            try:
                req = urllib.request.Request(api_url, headers={"User-Agent": "TTSx-Studio/1.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    tree = json.loads(resp.read().decode("utf-8"))
                    resolved_type = r_type
                    break
            except Exception as e:
                last_err = e

        if tree is None:
            raise Exception(f"Không thể quét repository ({repo_id}): {last_err}")

        local_piper_dir = Path(models_path("piper"))
        onnx_entries: Dict[str, dict] = {}
        json_entries: Dict[str, dict] = {}

        for item in tree:
            path = item.get("path", "")
            if path.endswith(".onnx"):
                onnx_entries[path] = item
            elif path.endswith(".onnx.json") or path.endswith(".json"):
                json_entries[path] = item

        results: List[VoiceModelItem] = []
        for onnx_path, item in onnx_entries.items():
            p = Path(onnx_path)
            stem_name = p.stem
            size_bytes = item.get("size", 0)

            # Look for matching json
            json_candidate = str(p.with_suffix(".onnx.json")).replace("\\", "/")
            if json_candidate not in json_entries:
                json_candidate = str(p.with_suffix(".json")).replace("\\", "/")
            if json_candidate not in json_entries:
                parent_config = str(p.parent / "config.json").replace("\\", "/")
                if parent_config in json_entries:
                    json_candidate = parent_config
                elif "config.json" in json_entries:
                    json_candidate = "config.json"

            has_json = json_candidate in json_entries

            if resolved_type == "bucket":
                onnx_url = f"https://huggingface.co/buckets/{repo_id}/resolve/{onnx_path}?download=true"
                json_url = f"https://huggingface.co/buckets/{repo_id}/resolve/{json_candidate}?download=true" if has_json else ""
            else:
                onnx_url = f"https://huggingface.co/{repo_id}/resolve/main/{onnx_path}"
                json_url = f"https://huggingface.co/{repo_id}/resolve/main/{json_candidate}" if has_json else f"{onnx_url}.json"

            # Determine language only if explicit in path or repository context
            lang_code = ""
            lang_name = ""
            m_lang = re.search(r"(?:^|[/_\-])(vi_vn|vi|en_us|en_gb|en|ja_jp|ja|zh_cn|zh|fr_fr|fr|de_de|de|es_es|es|ko_kr|ko|ru_ru|ru)(?:[/_\-]|\.|$)", onnx_path.lower())
            if m_lang:
                raw_code = m_lang.group(1).lower().split("_")[0]
                lang_code = raw_code
                lang_names_map = {
                    "vi": "Tiếng Việt",
                    "en": "English",
                    "ja": "日本語",
                    "zh": "中文",
                    "fr": "Français",
                    "de": "Deutsch",
                    "es": "Español",
                    "ko": "한국어",
                    "ru": "Русский",
                }
                lang_name = lang_names_map.get(raw_code, raw_code.upper())
            elif any(k in repo_id.lower() for k in ("vtranslate", "bonelag", "viet", "nghit", "mailinh")):
                lang_code = "vi"
                lang_name = "Tiếng Việt"

            # Determine gender only if explicit in filename or recognized name
            gender = ""
            stem_lower = stem_name.lower()
            if re.search(r"(?:^|[_/\-])(female|woman)(?:[_/\-]|\d|$)", stem_lower) or any(
                stem_lower.startswith(fn) for fn in ("hoaimy", "ngochuyen", "ngocngan", "maiphuong", "hongtuyen", "huyenngoc", "leyen", "banmai", "cuc")
            ):
                gender = "female"
            elif re.search(r"(?:^|[_/\-])(male|man)(?:[_/\-]|\d|$)", stem_lower) or any(
                stem_lower.startswith(mn) for mn in ("namminh", "namtutin", "dungdien", "duyoryx", "minhquang", "lacphi", "doanhdoanh", "chieuthanh")
            ):
                gender = "male"

            quality = "44.1kHz" if "44k" in stem_lower else ("High" if "high" in stem_lower else ("Medium" if "medium" in stem_lower else ("Low" if "low" in stem_lower else "")))

            model_filename = p.name
            json_filename = f"{model_filename}.json"
            local_onnx = local_piper_dir / model_filename
            local_json = local_piper_dir / json_filename
            is_downloaded = local_onnx.exists() and local_onnx.stat().st_size > 1024

            pretty_name = stem_name.replace("_", " ").replace("-", " ").capitalize()

            results.append(
                VoiceModelItem(
                    voice_id=stem_name,
                    name=pretty_name,
                    language_code=lang_code,
                    country_code="",
                    language_name=lang_name,
                    gender=gender,
                    quality=quality,
                    onnx_url=onnx_url,
                    json_url=json_url,
                    onnx_size_bytes=size_bytes,
                    is_downloaded=is_downloaded,
                    local_onnx_path=str(local_onnx),
                    local_json_path=str(local_json),
                    repo_source=repo_id,
                )
            )

        return results


class VoiceDownloadWorker(QThread):
    progress_signal = Signal(int, str)  # percent, speed/status string
    finished_signal = Signal(VoiceModelItem)
    error_signal = Signal(str)

    def __init__(self, item: VoiceModelItem):
        super().__init__()
        self.item = item
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            import glob
            import shutil

            onnx_target = Path(self.item.local_onnx_path)
            json_target = Path(self.item.local_json_path)
            onnx_target.parent.mkdir(parents=True, exist_ok=True)

            # 1. Download ONNX JSON config first
            self.progress_signal.emit(5, "Đang tải cấu hình config .json...")
            success_json = self._download_file(self.item.json_url, str(json_target))

            # Fallback if specific json failed or was missing on remote
            if not success_json or not json_target.exists() or json_target.stat().st_size <= 10:
                templates = glob.glob(str(onnx_target.parent / "*.onnx.json"))
                if templates:
                    shutil.copy(templates[0], str(json_target))

            # 2. Download ONNX model file
            self.progress_signal.emit(10, f"Đang tải model {self.item.name} ({format_size(self.item.onnx_size_bytes)})...")
            self._download_file_with_progress(self.item.onnx_url, str(onnx_target))

            # Guarantee json existence again after onnx is placed
            if not json_target.exists() or json_target.stat().st_size <= 10:
                templates = glob.glob(str(onnx_target.parent / "*.onnx.json"))
                if templates:
                    shutil.copy(templates[0], str(json_target))

            self.item.is_downloaded = True
            self.progress_signal.emit(100, "Hoàn tất tải về!")
            self.finished_signal.emit(self.item)
        except Exception as e:
            self.error_signal.emit(f"Lỗi tải {self.item.name}: {e}")

    def _download_file(self, url: str, dest: str) -> bool:
        try:
            safe_url = urllib.parse.quote(url, safe=":/?#[]@!$&()*+,;=")
            req = urllib.request.Request(safe_url, headers={"User-Agent": "TTSx-Studio/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
                if len(data) > 10:
                    with open(dest, "wb") as f:
                        f.write(data)
                    return True
        except Exception:
            pass
        return False

    def _download_file_with_progress(self, url: str, dest: str):
        safe_url = urllib.parse.quote(url, safe=":/?#[]@!$&()*+,;=")
        req = urllib.request.Request(safe_url, headers={"User-Agent": "TTSx-Studio/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            total_size = int(resp.headers.get("content-length", self.item.onnx_size_bytes or 0))
            downloaded = 0
            block_size = 64 * 1024
            start_time = time.time()

            temp_dest = f"{dest}.part"
            with open(temp_dest, "wb") as f:
                while True:
                    if self._is_cancelled:
                        raise RuntimeError("Đã hủy tải về.")
                    chunk = resp.read(block_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)

                    elapsed = max(0.1, time.time() - start_time)
                    speed_kb = (downloaded / 1024.0) / elapsed
                    speed_str = f"{speed_kb/1024:.1f} MB/s" if speed_kb >= 1024 else f"{speed_kb:.0f} KB/s"

                    if total_size > 0:
                        pct = int(min(99, 10 + (downloaded / total_size) * 88))
                        stat_msg = f"{format_size(downloaded)} / {format_size(total_size)} ({speed_str})"
                    else:
                        pct = 50
                        stat_msg = f"{format_size(downloaded)} ({speed_str})"

                    self.progress_signal.emit(pct, stat_msg)

            if os.path.exists(dest):
                try:
                    os.remove(dest)
                except OSError:
                    pass
            os.rename(temp_dest, dest)


class VoiceManagerDialog(QDialog):
    voices_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙️ Quản lý & Tải giọng đọc (Piper TTS)")
        self.resize(920, 620)
        self.setMinimumSize(780, 480)

        self.all_items: List[VoiceModelItem] = []
        self.filtered_items: List[VoiceModelItem] = []
        self.scan_worker: Optional[VoiceScanWorker] = None
        self.download_worker: Optional[VoiceDownloadWorker] = None
        self.active_download_item: Optional[VoiceModelItem] = None

        self._setup_ui()
        self._apply_dialog_theme()

        # Initial auto-scan of official repo
        self._start_scan("https://huggingface.co/rhasspy/piper-voices/tree/main")

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 1. Header & Source Repo Bar
        grp_source = QFrame()
        grp_source.setObjectName("SourceFrame")
        source_layout = QVBoxLayout(grp_source)
        source_layout.setContentsMargins(10, 10, 10, 10)
        source_layout.setSpacing(8)

        lbl_src = QLabel("🌐 Nguồn tải giọng đọc (Hugging Face Repository):")
        lbl_src.setStyleSheet("font-weight: bold; color: #4FC3F7;")
        source_layout.addWidget(lbl_src)

        url_row = QHBoxLayout()
        self.txt_repo_url = QLineEdit("https://huggingface.co/rhasspy/piper-voices/tree/main")
        self.txt_repo_url.setPlaceholderText("Dán link Hugging Face (ví dụ: https://huggingface.co/rhasspy/piper-voices hoặc user/repo)")
        self.txt_repo_url.returnPressed.connect(self._on_scan_clicked)
        url_row.addWidget(self.txt_repo_url)

        self.btn_scan = QPushButton("🔍 Quét Model")
        self.btn_scan.setObjectName("BtnScan")
        self.btn_scan.clicked.connect(self._on_scan_clicked)
        url_row.addWidget(self.btn_scan)
        source_layout.addLayout(url_row)

        # Quick preset buttons
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Kho giọng:"))
        
        btn_vtranslate = QPushButton("⚡ vTranslate (VI - 21 giọng)")
        btn_vtranslate.setStyleSheet("font-weight: bold; color: #80D8FF;")
        btn_vtranslate.clicked.connect(lambda: self._start_scan("https://huggingface.co/buckets/bonelag/vTranslate"))
        preset_row.addWidget(btn_vtranslate)

        btn_rhasspy = QPushButton("🌟 Rhasspy Piper (Gốc - 170+ giọng)")
        btn_rhasspy.clicked.connect(lambda: self._start_scan("https://huggingface.co/rhasspy/piper-voices/tree/main"))
        preset_row.addWidget(btn_rhasspy)

        btn_nghia = QPushButton("🇻🇳 NghiTTS (VI - 50 giọng)")
        btn_nghia.clicked.connect(lambda: self._start_scan("https://huggingface.co/doof-ferb/nghitts-copy"))
        preset_row.addWidget(btn_nghia)

        btn_mailinh = QPushButton("🇻🇳 MaiLinh TTS")
        btn_mailinh.clicked.connect(lambda: self._start_scan("https://huggingface.co/beyoru/MaiLinh-TTS-CoreML"))
        preset_row.addWidget(btn_mailinh)

        preset_row.addStretch()
        source_layout.addLayout(preset_row)

        layout.addWidget(grp_source)

        # 2. Filter Bar
        filter_row = QHBoxLayout()
        
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("🔍 Tìm kiếm tên giọng, mã ID...")
        self.txt_search.textChanged.connect(self._apply_filters)
        filter_row.addWidget(self.txt_search, stretch=2)

        # Language / Country Filter
        filter_row.addWidget(QLabel("Ngôn ngữ:"))
        self.cmb_lang = QComboBox()
        self.cmb_lang.addItem("Tất cả ngôn ngữ", "")
        self.cmb_lang.addItem("🇻🇳 Tiếng Việt (vi)", "vi")
        self.cmb_lang.addItem("🇬🇧 Tiếng Anh (en)", "en")
        self.cmb_lang.addItem("🇯🇵 Tiếng Nhật (ja)", "ja")
        self.cmb_lang.addItem("🇨🇳 Tiếng Trung (zh)", "zh")
        self.cmb_lang.addItem("🇫🇷 Tiếng Pháp (fr)", "fr")
        self.cmb_lang.addItem("🇩🇪 Tiếng Đức (de)", "de")
        self.cmb_lang.addItem("🇪🇸 Tiếng Tây Ban Nha (es)", "es")
        self.cmb_lang.addItem("🇰🇷 Tiếng Hàn (ko)", "ko")
        self.cmb_lang.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self.cmb_lang, stretch=1)

        # Gender Filter
        filter_row.addWidget(QLabel("Giới tính:"))
        self.cmb_gender = QComboBox()
        self.cmb_gender.addItem("Tất cả giới tính", "")
        self.cmb_gender.addItem("Nữ (Female)", "female")
        self.cmb_gender.addItem("Nam (Male)", "male")
        self.cmb_gender.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self.cmb_gender, stretch=1)

        # Download Status Filter
        filter_row.addWidget(QLabel("Trạng thái:"))
        self.cmb_status = QComboBox()
        self.cmb_status.addItem("Tất cả trạng thái", "")
        self.cmb_status.addItem("Chưa tải về", "not_downloaded")
        self.cmb_status.addItem("Đã có sẵn", "downloaded")
        self.cmb_status.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self.cmb_status, stretch=1)

        layout.addLayout(filter_row)

        # 3. Model Table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Tên giọng đọc",
            "Mã ID / File",
            "Ngôn ngữ",
            "Giới tính",
            "Chất lượng",
            "Dung lượng",
            "Hành động",
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table)

        # 4. Status Bar & Progress
        bottom_layout = QHBoxLayout()
        self.lbl_status = QLabel("Sẵn sàng.")
        self.lbl_status.setStyleSheet("color: #9E9E9E;")
        bottom_layout.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(12)
        bottom_layout.addWidget(self.progress_bar)

        self.btn_close = QPushButton("Đóng")
        self.btn_close.clicked.connect(self.accept)
        bottom_layout.addWidget(self.btn_close)

        layout.addLayout(bottom_layout)

    def _on_scan_clicked(self):
        url = self.txt_repo_url.text().strip()
        if not url:
            QMessageBox.warning(self, "Lỗi", "Vui lòng nhập link Hugging Face.")
            return
        self._start_scan(url)

    def _start_scan(self, repo_url: str):
        self.txt_repo_url.setText(repo_url)
        self.btn_scan.setEnabled(False)
        self.lbl_status.setText(f"Đang quét danh sách model từ {repo_url}...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate

        self.scan_worker = VoiceScanWorker(repo_url)
        self.scan_worker.progress_signal.connect(lambda msg: self.lbl_status.setText(msg))
        self.scan_worker.finished_signal.connect(self._on_scan_finished)
        self.scan_worker.error_signal.connect(self._on_scan_error)
        self.scan_worker.start()

    def _on_scan_finished(self, items: List[VoiceModelItem]):
        self.btn_scan.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.all_items = items
        self.lbl_status.setText(f"✅ Đã tìm thấy {len(items)} model giọng đọc.")
        self._apply_filters()

    def _on_scan_error(self, err_msg: str):
        self.btn_scan.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.lbl_status.setText(f"❌ Lỗi quét: {err_msg}")
        QMessageBox.critical(self, "Lỗi kết nối", f"Không thể quét repository:\n{err_msg}")

    def _apply_filters(self):
        search = self.txt_search.text().strip().lower()
        selected_lang = self.cmb_lang.currentData()
        selected_gender = self.cmb_gender.currentData()
        selected_status = self.cmb_status.currentData()

        filtered = []
        for item in self.all_items:
            # Search text match
            if search and (search not in item.name.lower() and search not in item.voice_id.lower()):
                continue

            # Language filter
            if selected_lang:
                if not item.language_code.lower().startswith(selected_lang.lower()):
                    continue

            # Gender filter
            if selected_gender:
                if selected_gender.lower() not in item.gender.lower():
                    continue

            # Status filter
            if selected_status == "downloaded" and not item.is_downloaded:
                continue
            if selected_status == "not_downloaded" and item.is_downloaded:
                continue

            filtered.append(item)

        self.filtered_items = filtered
        self._render_table()

    def _render_table(self):
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.filtered_items))

        for row, item in enumerate(self.filtered_items):
            # Name
            item_name = QTableWidgetItem(f"🎙️ {item.name}")
            item_name.setToolTip(item.onnx_url)
            self.table.setItem(row, 0, item_name)

            # ID
            item_id = QTableWidgetItem(item.voice_id)
            item_id.setForeground(Qt.gray)
            self.table.setItem(row, 1, item_id)

            # Language
            if item.language_code:
                if item.language_name:
                    lang_label = f"{item.language_code.upper()} ({item.language_name})"
                elif item.country_code:
                    lang_label = f"{item.language_code.upper()} ({item.country_code})"
                else:
                    lang_label = item.language_code.upper()
            else:
                lang_label = "—"
            self.table.setItem(row, 2, QTableWidgetItem(lang_label))

            # Gender
            g = (item.gender or "").strip().lower()
            if g in ("female", "f", "nữ"):
                gender_txt = "Nữ ♀"
            elif g in ("male", "m", "nam"):
                gender_txt = "Nam ♂"
            else:
                gender_txt = "—"
            self.table.setItem(row, 3, QTableWidgetItem(gender_txt))

            # Quality
            if item.quality and item.quality.lower() not in ("unknown", ""):
                qual_item = QTableWidgetItem(item.quality.capitalize())
                if item.quality.lower() in ("high", "44.1khz"):
                    qual_item.setForeground(Qt.cyan)
            else:
                qual_item = QTableWidgetItem("—")
            self.table.setItem(row, 4, qual_item)

            # Size
            self.table.setItem(row, 5, QTableWidgetItem(format_size(item.onnx_size_bytes)))

            # Action Button
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(4, 2, 4, 2)
            action_layout.setSpacing(4)

            if item.is_downloaded:
                btn_del = QPushButton("🗑️ Xóa")
                btn_del.setStyleSheet("background-color: #3b2024; color: #ff8a80; border: 1px solid #662228; border-radius: 4px; padding: 3px 8px;")
                btn_del.clicked.connect(lambda _, it=item: self._delete_voice(it))
                action_layout.addWidget(btn_del)
                status_lbl = QLabel("✅ Đã có")
                status_lbl.setStyleSheet("color: #81C784; font-weight: bold;")
                action_layout.addWidget(status_lbl)
            else:
                btn_down = QPushButton("⬇️ Tải về")
                btn_down.setStyleSheet("background-color: #0288D1; color: white; font-weight: bold; border-radius: 4px; padding: 3px 10px;")
                btn_down.clicked.connect(lambda _, it=item: self._download_voice(it))
                action_layout.addWidget(btn_down)

            self.table.setCellWidget(row, 6, action_widget)

    def _download_voice(self, item: VoiceModelItem):
        if self.download_worker and self.download_worker.isRunning():
            QMessageBox.information(self, "Đang tải", "Một tiến trình tải đang chạy. Vui lòng chờ hoàn tất.")
            return

        self.active_download_item = item
        self.lbl_status.setText(f"Đang tải {item.name}...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self.download_worker = VoiceDownloadWorker(item)
        self.download_worker.progress_signal.connect(self._on_download_progress)
        self.download_worker.finished_signal.connect(self._on_download_finished)
        self.download_worker.error_signal.connect(self._on_download_error)
        self.download_worker.start()

    def _on_download_progress(self, pct: int, msg: str):
        self.progress_bar.setValue(pct)
        self.lbl_status.setText(msg)

    def _on_download_finished(self, item: VoiceModelItem):
        self.progress_bar.setVisible(False)
        self.lbl_status.setText(f"🎉 Đã tải xong model: {item.name}")
        self._apply_filters()
        self.voices_changed.emit()

    def _on_download_error(self, err_msg: str):
        self.progress_bar.setVisible(False)
        self.lbl_status.setText(f"❌ {err_msg}")
        QMessageBox.critical(self, "Lỗi tải về", err_msg)

    def _delete_voice(self, item: VoiceModelItem):
        reply = QMessageBox.question(
            self,
            "Xác nhận xóa",
            f"Bạn có chắc muốn xóa model '{item.name}' ({os.path.basename(item.local_onnx_path)})?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                if os.path.exists(item.local_onnx_path):
                    os.remove(item.local_onnx_path)
                if os.path.exists(item.local_json_path):
                    os.remove(item.local_json_path)
                item.is_downloaded = False
                self._apply_filters()
                self.voices_changed.emit()
                self.lbl_status.setText(f"Đã xóa model {item.name}.")
            except Exception as e:
                QMessageBox.critical(self, "Lỗi xóa file", str(e))

    def _apply_dialog_theme(self):
        self.setStyleSheet("""
        QDialog {
            background-color: #1a1a22;
            color: #e0e0e0;
        }
        QFrame#SourceFrame {
            background-color: #22222c;
            border: 1px solid #333342;
            border-radius: 8px;
        }
        QLineEdit, QComboBox {
            background-color: #141419;
            border: 1px solid #363646;
            border-radius: 6px;
            padding: 5px 8px;
            color: #ffffff;
        }
        QLineEdit:focus, QComboBox:focus {
            border: 1px solid #4FC3F7;
        }
        QTableWidget {
            background-color: #16161c;
            border: 1px solid #333342;
            border-radius: 6px;
            gridline-color: #262632;
            color: #ffffff;
        }
        QHeaderView::section {
            background-color: #22222c;
            color: #4FC3F7;
            font-weight: bold;
            padding: 6px;
            border: 1px solid #2d2d3a;
        }
        QTableWidget::item:selected {
            background-color: #1e3348;
        }
        QPushButton {
            background-color: #282834;
            border: 1px solid #3d3d50;
            border-radius: 6px;
            padding: 5px 10px;
            color: #ffffff;
        }
        QPushButton:hover {
            background-color: #38384a;
        }
        QPushButton#BtnScan {
            background-color: #0288D1;
            font-weight: bold;
        }
        QPushButton#BtnScan:hover {
            background-color: #039BE5;
        }
        QProgressBar {
            border: 1px solid #333340;
            border-radius: 4px;
            background-color: #141419;
            text-align: center;
        }
        QProgressBar::chunk {
            background-color: #4FC3F7;
            border-radius: 3px;
        }
        """)
