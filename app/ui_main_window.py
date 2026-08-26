import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, QTime, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QPalette
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .runtime_paths import app_path
from .tts_engine import TTSEngine, VoiceInfo


class NoScrollComboBox(QComboBox):
    """ComboBox ignoring wheelEvent to prevent accidental selection changes during mouse scroll."""
    def wheelEvent(self, event):
        event.ignore()


class NoScrollSlider(QSlider):
    """Slider ignoring wheelEvent so scrolling the mouse scrolls the parent panel instead."""
    def wheelEvent(self, event):
        event.ignore()


class NoScrollSpinBox(QSpinBox):
    """SpinBox ignoring wheelEvent to prevent value changes during mouse scroll."""
    def wheelEvent(self, event):
        event.ignore()


class SynthesisWorker(QThread):
    progress_signal = Signal(str)
    finished_signal = Signal(dict)
    error_signal = Signal(str)

    def __init__(
        self,
        engine: TTSEngine,
        text: str,
        output_path: str,
        voice_id: str,
        speed: float = 1.0,
        pitch: int = 0,
        output_format: str = "wav",
        piper_options: Optional[dict] = None,
    ):
        super().__init__()
        self.engine = engine
        self.text = text
        self.output_path = output_path
        self.voice_id = voice_id
        self.speed = speed
        self.pitch = pitch
        self.output_format = output_format
        self.piper_options = piper_options

    def run(self):
        try:
            result = self.engine.synthesize(
                text=self.text,
                output_path=self.output_path,
                voice_id=self.voice_id,
                speed=self.speed,
                pitch=self.pitch,
                output_format=self.output_format,
                piper_options=self.piper_options,
                on_progress=lambda msg: self.progress_signal.emit(msg),
            )
            self.finished_signal.emit(result)
        except Exception as e:
            self.error_signal.emit(str(e))


class TTSMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TTSx - Studio (Standalone)")
        
        # Fit comfortably within available screen area (excluding Windows Taskbar)
        screen = QGuiApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            target_w = min(1140, max(880, int(avail.width() * 0.88)))
            target_h = min(710, max(540, int(avail.height() * 0.88)))
            self.resize(target_w, target_h)
            self.setMinimumSize(860, 500)
            x = avail.x() + (avail.width() - target_w) // 2
            y = avail.y() + (avail.height() - target_h) // 2
            self.setGeometry(x, y, target_w, target_h)
        else:
            self.resize(1080, 680)
            self.setMinimumSize(860, 500)

        self.engine = TTSEngine()
        self.current_audio_path: Optional[str] = None
        self.worker: Optional[SynthesisWorker] = None

        # Setup Audio Player
        self.media_player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.media_player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.9)

        self.media_player.positionChanged.connect(self._on_player_position_changed)
        self.media_player.durationChanged.connect(self._on_player_duration_changed)
        self.media_player.playbackStateChanged.connect(self._on_player_state_changed)

        self._setup_ui()
        self._apply_dark_theme()
        self._populate_voices()

    def _setup_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # Header Bar
        header_layout = QHBoxLayout()
        header_title = QLabel("🎙️ TTSx Studio")
        header_title.setObjectName("HeaderTitle")
        header_title.setStyleSheet("font-size: 20px; font-weight: bold; color: #4FC3F7;")
        header_layout.addWidget(header_title)

        header_layout.addStretch()

        self.btn_download_voices = QPushButton("⚙️ Tải thêm giọng đọc")
        self.btn_download_voices.setToolTip("Mở giao diện tìm kiếm và tải thêm giọng đọc Piper TTS từ Hugging Face")
        self.btn_download_voices.setStyleSheet("background-color: #0288D1; font-weight: bold;")
        self.btn_download_voices.clicked.connect(self._open_voice_manager)
        header_layout.addWidget(self.btn_download_voices)

        self.btn_open_out_dir = QPushButton("📁 Mở thư mục Output")
        self.btn_open_out_dir.clicked.connect(self._open_output_directory)
        header_layout.addWidget(self.btn_open_out_dir)

        main_layout.addLayout(header_layout)

        # Splitter between Left (Text Input) and Right (Voice & Controls)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        # LEFT PANEL: Text Input
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(10)

        lbl_input = QLabel("📝 Văn bản cần chuyển thành giọng nói:")
        lbl_input.setStyleSheet("font-weight: bold; font-size: 14px;")
        left_layout.addWidget(lbl_input)

        self.txt_input = QTextEdit()
        self.txt_input.setPlaceholderText(
            "Nhập hoặc dán văn bản tại đây...\n\n"
            "Ví dụ:\n"
            "Xin chào các bạn! Hôm nay là ngày 23/08/2026. TTSx Studio hỗ trợ đọc cả tiếng Việt và tiếng Anh mượt mà."
        )
        self.txt_input.textChanged.connect(self._update_text_stats)
        left_layout.addWidget(self.txt_input)

        # Text Toolbar
        txt_tools_layout = QHBoxLayout()
        self.lbl_stats = QLabel("0 từ | 0 ký tự | Dự kiến: ~0s")
        self.lbl_stats.setStyleSheet("color: #9E9E9E; font-size: 12px;")
        txt_tools_layout.addWidget(self.lbl_stats)

        txt_tools_layout.addStretch()

        self.btn_import_txt = QPushButton("📄 Nạp từ file .txt")
        self.btn_import_txt.clicked.connect(self._import_txt_file)
        txt_tools_layout.addWidget(self.btn_import_txt)

        self.btn_preview_norm = QPushButton("🔍 Chuẩn hóa tiếng Việt")
        self.btn_preview_norm.setToolTip("Xem trước văn bản sau khi chuẩn hóa số, ngày tháng, từ viết tắt")
        self.btn_preview_norm.clicked.connect(self._preview_normalized_text)
        txt_tools_layout.addWidget(self.btn_preview_norm)

        self.btn_clear_txt = QPushButton("🗑️ Xóa")
        self.btn_clear_txt.clicked.connect(self.txt_input.clear)
        txt_tools_layout.addWidget(self.btn_clear_txt)

        left_layout.addLayout(txt_tools_layout)
        splitter.addWidget(left_widget)

        # RIGHT PANEL: Controls, Voice Selection, Player
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(6, 2, 14, 8)
        right_layout.setSpacing(12)

        # 1. Voice Settings Group
        grp_voice = QGroupBox("🔊 Chọn giọng đọc (Voice)")
        grp_voice_layout = QVBoxLayout(grp_voice)
        grp_voice_layout.setSpacing(8)

        # Filters: Language & Provider
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Ngôn ngữ:"))
        self.cmb_lang_filter = NoScrollComboBox()
        self.cmb_lang_filter.addItems(["Tất cả", "Tiếng Việt (vi)", "Tiếng Anh (en)"])
        self.cmb_lang_filter.currentIndexChanged.connect(self._populate_voices)
        filter_layout.addWidget(self.cmb_lang_filter)

        filter_layout.addWidget(QLabel("Nguồn:"))
        self.cmb_prov_filter = NoScrollComboBox()
        self.cmb_prov_filter.addItems(["Tất cả", "Piper (Offline)", "Edge (Online)"])
        self.cmb_prov_filter.currentIndexChanged.connect(self._populate_voices)
        filter_layout.addWidget(self.cmb_prov_filter)

        grp_voice_layout.addLayout(filter_layout)

        # Search / Quick Filter
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Tìm kiếm:"))
        self.txt_search_voice = QLineEdit()
        self.txt_search_voice.setPlaceholderText("Lọc theo tên giọng đọc...")
        self.txt_search_voice.textChanged.connect(self._filter_voices_by_search)
        search_layout.addWidget(self.txt_search_voice)
        grp_voice_layout.addLayout(search_layout)

        # Voice Selector
        self.cmb_voices = NoScrollComboBox()
        self.cmb_voices.currentIndexChanged.connect(self._on_voice_changed)
        grp_voice_layout.addWidget(self.cmb_voices)

        # Voice Info Badge
        self.lbl_voice_info = QLabel("Thông tin giọng: -")
        self.lbl_voice_info.setStyleSheet("color: #81D4FA; font-size: 12px;")
        grp_voice_layout.addWidget(self.lbl_voice_info)

        right_layout.addWidget(grp_voice)

        # 2. Audio Parameter Group
        grp_params = QGroupBox("⚙️ Tùy chọn giọng đọc && Định dạng")
        grp_params_layout = QVBoxLayout(grp_params)
        grp_params_layout.setSpacing(8)

        # Speed Slider
        speed_layout = QHBoxLayout()
        speed_layout.addWidget(QLabel("Tốc độ đọc:"))
        self.lbl_speed_val = QLabel("1.00x")
        self.lbl_speed_val.setStyleSheet("font-weight: bold; color: #4FC3F7; min-width: 45px;")
        speed_layout.addWidget(self.lbl_speed_val)

        self.slider_speed = NoScrollSlider(Qt.Horizontal)
        self.slider_speed.setRange(50, 200)
        self.slider_speed.setValue(100)
        self.slider_speed.setSingleStep(5)
        self.slider_speed.valueChanged.connect(self._on_speed_changed)
        speed_layout.addWidget(self.slider_speed)

        self.btn_reset_speed = QPushButton("1.0x")
        self.btn_reset_speed.setMaximumWidth(50)
        self.btn_reset_speed.clicked.connect(lambda: self.slider_speed.setValue(100))
        speed_layout.addWidget(self.btn_reset_speed)

        grp_params_layout.addLayout(speed_layout)

        # Pitch Slider
        pitch_layout = QHBoxLayout()
        pitch_layout.addWidget(QLabel("Cao độ (Pitch):"))
        self.lbl_pitch_val = QLabel("+0Hz")
        self.lbl_pitch_val.setStyleSheet("font-weight: bold; color: #4FC3F7; min-width: 45px;")
        pitch_layout.addWidget(self.lbl_pitch_val)

        self.slider_pitch = NoScrollSlider(Qt.Horizontal)
        self.slider_pitch.setRange(-50, 50)
        self.slider_pitch.setValue(0)
        self.slider_pitch.setSingleStep(1)
        self.slider_pitch.valueChanged.connect(self._on_pitch_changed)
        pitch_layout.addWidget(self.slider_pitch)

        self.btn_reset_pitch = QPushButton("0Hz")
        self.btn_reset_pitch.setMaximumWidth(50)
        self.btn_reset_pitch.clicked.connect(lambda: self.slider_pitch.setValue(0))
        pitch_layout.addWidget(self.btn_reset_pitch)

        grp_params_layout.addLayout(pitch_layout)

        # Format & Output Choice
        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel("Định dạng xuất:"))
        self.cmb_format = NoScrollComboBox()
        self.cmb_format.addItems(["WAV (Gốc - Lossless PCM)", "MP3 (192kbps - Nén)"])
        format_layout.addWidget(self.cmb_format)
        format_layout.addStretch()
        grp_params_layout.addLayout(format_layout)

        right_layout.addWidget(grp_params)

        # 2.5 Advanced Piper Settings (Collapsible)
        self.btn_toggle_adv = QPushButton("▶ Cài đặt nâng cao (Piper TTS)")
        self.btn_toggle_adv.setCheckable(True)
        self.btn_toggle_adv.setChecked(False)
        self.btn_toggle_adv.setObjectName("BtnToggleAdv")
        self.btn_toggle_adv.setStyleSheet(
            "QPushButton#BtnToggleAdv {"
            "  text-align: left;"
            "  padding: 6px 10px;"
            "  font-weight: bold;"
            "  background-color: #262633;"
            "  border: 1px solid #3d3d52;"
            "  border-radius: 4px;"
            "  color: #81D4FA;"
            "}"
            "QPushButton#BtnToggleAdv:hover {"
            "  background-color: #323244;"
            "}"
            "QPushButton#BtnToggleAdv:checked {"
            "  background-color: #1e2836;"
            "  border-color: #0288D1;"
            "  color: #4FC3F7;"
            "}"
        )
        self.btn_toggle_adv.toggled.connect(self._toggle_advanced_settings)
        right_layout.addWidget(self.btn_toggle_adv)

        self.widget_adv = QFrame()
        self.widget_adv.setObjectName("WidgetAdv")
        self.widget_adv.setStyleSheet(
            "QFrame#WidgetAdv {"
            "  background-color: #1c1c24;"
            "  border: 1px solid #333345;"
            "  border-radius: 6px;"
            "  padding: 6px;"
            "}"
        )
        self.widget_adv.setVisible(False)
        adv_layout = QVBoxLayout(self.widget_adv)
        adv_layout.setSpacing(6)
        adv_layout.setContentsMargins(6, 6, 6, 6)

        # Presets Row
        presets_layout = QHBoxLayout()
        presets_layout.setSpacing(6)
        lbl_preset = QLabel("Preset:")
        lbl_preset.setStyleSheet("font-weight: bold; color: #90CAF9;")
        presets_layout.addWidget(lbl_preset)

        btn_style = "QPushButton { padding: 4px 10px; font-size: 12px; border-radius: 4px; } QPushButton:hover { background-color: #0288D1; }"

        self.btn_preset_warm = QPushButton("☕ Ấm && Mượt")
        self.btn_preset_warm.setStyleSheet(btn_style)
        self.btn_preset_warm.setToolTip("Tối ưu cho giọng nữ cao/the thé (như Ngọc Huyền): noise_scale=0.33, noise_w=0.50, length_scale=1.08 để giọng ấm, đầm và giảm chói tai")
        self.btn_preset_warm.clicked.connect(self._apply_preset_warm)
        presets_layout.addWidget(self.btn_preset_warm)

        self.btn_preset_clear = QPushButton("🎯 Rõ nét")
        self.btn_preset_clear.setStyleSheet(btn_style)
        self.btn_preset_clear.setToolTip("Thiết lập noise_scale=0.35, noise_w=0.45 để phát âm chính xác, không nuốt âm")
        self.btn_preset_clear.clicked.connect(self._apply_preset_clear)
        presets_layout.addWidget(self.btn_preset_clear)

        self.btn_preset_default = QPushButton("🔄 Mặc định")
        self.btn_preset_default.setStyleSheet(btn_style)
        self.btn_preset_default.setToolTip("Khôi phục thông số mặc định của Piper")
        self.btn_preset_default.clicked.connect(self._apply_preset_default)
        presets_layout.addWidget(self.btn_preset_default)
        presets_layout.addStretch()
        adv_layout.addLayout(presets_layout)

        # 1. noise_scale Slider
        noise_layout = QHBoxLayout()
        noise_layout.addWidget(QLabel("Nhiễu âm (noise_scale):"))
        self.lbl_noise_scale_val = QLabel("0.67")
        self.lbl_noise_scale_val.setStyleSheet("font-weight: bold; color: #4FC3F7; min-width: 38px;")
        noise_layout.addWidget(self.lbl_noise_scale_val)
        self.slider_noise_scale = NoScrollSlider(Qt.Horizontal)
        self.slider_noise_scale.setRange(0, 150)
        self.slider_noise_scale.setValue(67)
        self.slider_noise_scale.setToolTip("Giảm (0.3-0.4) giúp phát âm sắc nét, chuẩn xác, không rè. Tăng để tăng độ ngẫu nhiên.")
        self.slider_noise_scale.valueChanged.connect(self._on_noise_scale_changed)
        noise_layout.addWidget(self.slider_noise_scale)
        adv_layout.addLayout(noise_layout)

        # 2. noise_w_scale Slider
        noise_w_layout = QHBoxLayout()
        noise_w_layout.addWidget(QLabel("Thời lượng (noise_w):"))
        self.lbl_noise_w_val = QLabel("0.80")
        self.lbl_noise_w_val.setStyleSheet("font-weight: bold; color: #4FC3F7; min-width: 38px;")
        noise_w_layout.addWidget(self.lbl_noise_w_val)
        self.slider_noise_w = NoScrollSlider(Qt.Horizontal)
        self.slider_noise_w.setRange(0, 150)
        self.slider_noise_w.setValue(80)
        self.slider_noise_w.setToolTip("Giảm (0.4-0.5) giúp nhịp đọc ổn định, không nuốt phụ âm đuôi.")
        self.slider_noise_w.valueChanged.connect(self._on_noise_w_changed)
        noise_w_layout.addWidget(self.slider_noise_w)
        adv_layout.addLayout(noise_w_layout)

        # 3. length_scale Slider
        length_layout = QHBoxLayout()
        length_layout.addWidget(QLabel("Giãn âm (length_scale):"))
        self.lbl_length_scale_val = QLabel("1.00x")
        self.lbl_length_scale_val.setStyleSheet("font-weight: bold; color: #4FC3F7; min-width: 38px;")
        length_layout.addWidget(self.lbl_length_scale_val)
        self.slider_length_scale = NoScrollSlider(Qt.Horizontal)
        self.slider_length_scale.setRange(50, 200)
        self.slider_length_scale.setValue(100)
        self.slider_length_scale.setToolTip("Độ giãn thời lượng âm vị. 1.0 = tự động theo tốc độ chính.")
        self.slider_length_scale.valueChanged.connect(self._on_length_scale_changed)
        length_layout.addWidget(self.slider_length_scale)
        adv_layout.addLayout(length_layout)

        # 4. sentence_silence Slider
        silence_layout = QHBoxLayout()
        silence_layout.addWidget(QLabel("Khoảng lặng (silence):"))
        self.lbl_silence_val = QLabel("0.25s")
        self.lbl_silence_val.setStyleSheet("font-weight: bold; color: #4FC3F7; min-width: 38px;")
        silence_layout.addWidget(self.lbl_silence_val)
        self.slider_silence = NoScrollSlider(Qt.Horizontal)
        self.slider_silence.setRange(0, 100)
        self.slider_silence.setValue(25)
        self.slider_silence.setToolTip("Khoảng lặng đệm giữa các câu hoặc cuối audio để chống cụt âm.")
        self.slider_silence.valueChanged.connect(self._on_silence_changed)
        silence_layout.addWidget(self.slider_silence)
        adv_layout.addLayout(silence_layout)

        # 5. Checkboxes Row
        chk_layout = QHBoxLayout()
        chk_layout.setSpacing(8)
        self.chk_normalize = QCheckBox("Chuẩn hóa")
        self.chk_normalize.setChecked(True)
        self.chk_normalize.setToolTip("Chuẩn hóa biên độ âm lượng đỉnh để chống vỡ tiếng.")
        chk_layout.addWidget(self.chk_normalize)

        self.chk_warm_dsp = QCheckBox("🎧 Khử chói && Tăng ấm (DSP)")
        self.chk_warm_dsp.setChecked(False)
        self.chk_warm_dsp.setToolTip("Áp dụng bộ lọc Studio Warm: tăng dải trầm 210Hz, triệt tiêu gai chói 3.4kHz & 6.2kHz, loại bỏ tiếng the thé kim loại.")
        chk_layout.addWidget(self.chk_warm_dsp)

        self.chk_custom_dsp = QCheckBox("🛠️ Custom FFmpeg")
        self.chk_custom_dsp.setChecked(False)
        self.chk_custom_dsp.setToolTip("Bật ô nhập để dán chuỗi filter -af FFmpeg tùy biến (như Deep Warm, Tube Warmth,...).")
        self.chk_custom_dsp.toggled.connect(self._toggle_custom_dsp)
        chk_layout.addWidget(self.chk_custom_dsp)

        chk_layout.addStretch()
        adv_layout.addLayout(chk_layout)

        # Custom DSP Input Box
        self.txt_custom_dsp = QLineEdit()
        self.txt_custom_dsp.setPlaceholderText("Dán chuỗi filter -af (Ví dụ: volume=0.85,equalizer=f=190:t=q:w=0.9:g=5.0,...)")
        self.txt_custom_dsp.setStyleSheet("padding: 5px 8px; font-family: Consolas, monospace; font-size: 11px; background-color: #14141c; border: 1px solid #3d3d52; border-radius: 4px; color: #80D8FF;")
        self.txt_custom_dsp.setVisible(False)
        adv_layout.addWidget(self.txt_custom_dsp)

        # 6. Speaker ID Row
        spk_layout = QHBoxLayout()
        spk_layout.addWidget(QLabel("Speaker ID:"))
        self.spin_speaker_id = NoScrollSpinBox()
        self.spin_speaker_id.setRange(0, 99)
        self.spin_speaker_id.setValue(0)
        self.spin_speaker_id.setMinimumWidth(65)
        self.spin_speaker_id.setMaximumWidth(75)
        self.spin_speaker_id.setAlignment(Qt.AlignCenter)
        self.spin_speaker_id.setToolTip("Chỉ số giọng cho model có nhiều người nói (multi-speaker).")
        spk_layout.addWidget(self.spin_speaker_id)
        spk_layout.addStretch()
        adv_layout.addLayout(spk_layout)

        right_layout.addWidget(self.widget_adv)

        # 3. Synthesis Action & Progress
        self.btn_synthesize = QPushButton("✨ Tổng hợp giọng nói (Generate Audio)")
        self.btn_synthesize.setObjectName("BtnSynthesize")
        self.btn_synthesize.setStyleSheet(
            "QPushButton#BtnSynthesize {"
            "  background-color: #0288D1;"
            "  color: white;"
            "  font-weight: bold;"
            "  font-size: 15px;"
            "  padding: 10px;"
            "  border-radius: 6px;"
            "}"
            "QPushButton#BtnSynthesize:hover {"
            "  background-color: #039BE5;"
            "}"
            "QPushButton#BtnSynthesize:pressed {"
            "  background-color: #01579B;"
            "}"
            "QPushButton#BtnSynthesize:disabled {"
            "  background-color: #424242;"
            "  color: #757575;"
            "}"
        )
        self.btn_synthesize.clicked.connect(self._start_synthesis)
        right_layout.addWidget(self.btn_synthesize)

        # Progress bar and status
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(False)
        right_layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("Sẵn sàng.")
        self.lbl_status.setStyleSheet("color: #B0BEC5; font-size: 12px;")
        right_layout.addWidget(self.lbl_status)

        # 4. Audio Player & Export Group
        grp_player = QGroupBox("🎧 Trình phát && Lưu file")
        grp_player_layout = QVBoxLayout(grp_player)
        grp_player_layout.setSpacing(8)

        # Player Timeline
        time_layout = QHBoxLayout()
        self.lbl_curr_time = QLabel("00:00")
        self.lbl_curr_time.setStyleSheet("font-size: 11px; color: #90CAF9;")
        time_layout.addWidget(self.lbl_curr_time)

        self.slider_timeline = NoScrollSlider(Qt.Horizontal)
        self.slider_timeline.setRange(0, 1000)
        self.slider_timeline.sliderMoved.connect(self._on_seek_timeline)
        time_layout.addWidget(self.slider_timeline)

        self.lbl_total_time = QLabel("00:00")
        self.lbl_total_time.setStyleSheet("font-size: 11px; color: #90CAF9;")
        time_layout.addWidget(self.lbl_total_time)

        grp_player_layout.addLayout(time_layout)

        # Player Controls
        controls_layout = QHBoxLayout()
        self.btn_play_pause = QPushButton("▶ Phát")
        self.btn_play_pause.setEnabled(False)
        self.btn_play_pause.clicked.connect(self._toggle_playback)
        controls_layout.addWidget(self.btn_play_pause)

        self.btn_stop = QPushButton("⏹ Dừng")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_playback)
        controls_layout.addWidget(self.btn_stop)

        controls_layout.addSpacing(10)
        controls_layout.addWidget(QLabel("Âm lượng:"))
        self.slider_volume = NoScrollSlider(Qt.Horizontal)
        self.slider_volume.setRange(0, 100)
        self.slider_volume.setValue(90)
        self.slider_volume.setMaximumWidth(90)
        self.slider_volume.valueChanged.connect(self._on_volume_changed)
        controls_layout.addWidget(self.slider_volume)

        grp_player_layout.addLayout(controls_layout)

        # Save As Action
        save_layout = QHBoxLayout()
        self.btn_save_as = QPushButton("💾 Lưu tệp âm thanh...")
        self.btn_save_as.setEnabled(False)
        self.btn_save_as.clicked.connect(self._save_audio_as)
        save_layout.addWidget(self.btn_save_as)

        self.btn_open_file = QPushButton("📂 Mở file")
        self.btn_open_file.setEnabled(False)
        self.btn_open_file.clicked.connect(self._open_current_audio_file)
        save_layout.addWidget(self.btn_open_file)

        grp_player_layout.addLayout(save_layout)

        right_layout.addWidget(grp_player)

        scroll_right = QScrollArea()
        scroll_right.setWidgetResizable(True)
        scroll_right.setFrameShape(QFrame.NoFrame)
        scroll_right.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_right.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_right.setWidget(right_widget)

        splitter.addWidget(scroll_right)
        splitter.setSizes([480, 560])
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 5)
        main_layout.addWidget(splitter)

    def _apply_dark_theme(self):
        assets_dir = Path(app_path("assets"))
        up_arrow = (assets_dir / "arrow_up.svg").as_posix()
        down_arrow = (assets_dir / "arrow_down.svg").as_posix()

        dark_stylesheet = """
        QWidget {
            background-color: #1e1e24;
            color: #e0e0e0;
            font-family: 'Segoe UI', 'Roboto', 'Arial', sans-serif;
            font-size: 13px;
        }
        QLabel {
            background-color: transparent;
            border: none;
            color: #e0e0e0;
        }
        QCheckBox, QRadioButton {
            background-color: transparent;
            border: none;
            color: #e0e0e0;
        }
        QScrollArea, QScrollArea > QWidget > QWidget {
            background-color: transparent;
        }
        QGroupBox {
            font-weight: bold;
            border: 1px solid #33333e;
            border-radius: 8px;
            margin-top: 12px;
            padding: 12px;
            background-color: #25252d;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 12px;
            padding: 0 4px;
            color: #4FC3F7;
        }
        QTextEdit, QLineEdit, QComboBox {
            background-color: #16161a;
            border: 1px solid #3a3a48;
            border-radius: 6px;
            padding: 6px;
            color: #ffffff;
            selection-background-color: #0288D1;
        }
        QTextEdit:focus, QLineEdit:focus, QComboBox:focus {
            border: 1px solid #4FC3F7;
        }
        QSpinBox {
            background-color: #16161a;
            border: 1px solid #3a3a48;
            border-radius: 6px;
            padding: 4px 22px 4px 6px;
            color: #ffffff;
            font-weight: bold;
        }
        QSpinBox:focus {
            border: 1px solid #4FC3F7;
        }
        QSpinBox::up-button {
            subcontrol-origin: border;
            subcontrol-position: top right;
            width: 18px;
            border-left: 1px solid #3a3a48;
            border-bottom: 1px solid #3a3a48;
            border-top-right-radius: 5px;
            background-color: #22222d;
        }
        QSpinBox::down-button {
            subcontrol-origin: border;
            subcontrol-position: bottom right;
            width: 18px;
            border-left: 1px solid #3a3a48;
            border-bottom-right-radius: 5px;
            background-color: #22222d;
        }
        QSpinBox::up-button:hover, QSpinBox::down-button:hover {
            background-color: #38384d;
        }
        QSpinBox::up-arrow {
            image: url('__UP_ARROW__');
            width: 9px;
            height: 6px;
        }
        QSpinBox::down-arrow {
            image: url('__DOWN_ARROW__');
            width: 9px;
            height: 6px;
        }
        QComboBox::drop-down {
            border: none;
            width: 20px;
        }
        QComboBox QAbstractItemView {
            background-color: #25252d;
            border: 1px solid #3a3a48;
            selection-background-color: #0288D1;
            color: #ffffff;
        }
        QPushButton {
            background-color: #2d2d38;
            border: 1px solid #444455;
            border-radius: 6px;
            padding: 6px 12px;
            color: #ffffff;
        }
        QPushButton:hover {
            background-color: #3b3b4a;
            border-color: #55556a;
        }
        QPushButton:pressed {
            background-color: #1a1a22;
        }
        QPushButton:disabled {
            background-color: #202026;
            color: #555566;
            border-color: #2a2a35;
        }
        QSlider::groove:horizontal {
            border: 1px solid #333340;
            height: 6px;
            background: #16161a;
            margin: 2px 0;
            border-radius: 3px;
        }
        QSlider::sub-page:horizontal {
            background: #0288D1;
            border-radius: 3px;
        }
        QSlider::handle:horizontal {
            background: #4FC3F7;
            border: 1px solid #81D4FA;
            width: 14px;
            margin-top: -5px;
            margin-bottom: -5px;
            border-radius: 7px;
        }
        QProgressBar {
            border: 1px solid #333340;
            border-radius: 4px;
            text-align: center;
            background-color: #16161a;
            height: 8px;
        }
        QProgressBar::chunk {
            background-color: #4FC3F7;
            border-radius: 3px;
        }
        QScrollBar:vertical {
            background-color: #1a1a22;
            width: 8px;
            margin: 2px 0px 2px 0px;
            border-radius: 4px;
        }
        QScrollBar::handle:vertical {
            background-color: #38384d;
            min-height: 25px;
            border-radius: 4px;
        }
        QScrollBar::handle:vertical:hover {
            background-color: #4FC3F7;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
            border: none;
            background: none;
        }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
            background: none;
        }
        """.replace("__UP_ARROW__", up_arrow).replace("__DOWN_ARROW__", down_arrow)
        self.setStyleSheet(dark_stylesheet)

    def _get_settings_file(self) -> Path:
        return Path(__file__).resolve().parent / "setting.json"

    def _load_saved_voice_id(self) -> Optional[str]:
        try:
            p = self._get_settings_file()
            if p.is_file() and p.stat().st_size > 0:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("selected_voice")
        except Exception:
            pass
        return None

    def _save_saved_voice_id(self, voice_id: str):
        try:
            p = self._get_settings_file()
            data = {}
            if p.is_file() and p.stat().st_size > 0:
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = {}
            data["selected_voice"] = voice_id
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _populate_voices(self, select_voice_id: Optional[str] = None):
        lang_idx = self.cmb_lang_filter.currentIndex()
        prov_idx = self.cmb_prov_filter.currentIndex()

        lang_filter = None
        if lang_idx == 1:
            lang_filter = "vi"
        elif lang_idx == 2:
            lang_filter = "en"

        prov_filter = None
        if prov_idx == 1:
            prov_filter = "piper"
        elif prov_idx == 2:
            prov_filter = "edge"

        voices = self.engine.get_voices(provider=prov_filter, language=lang_filter)
        search_text = self.txt_search_voice.text().strip().lower()
        if search_text:
            voices = [v for v in voices if search_text in v.name.lower() or search_text in v.id.lower()]

        target_voice = select_voice_id or self.cmb_voices.currentData() or self._load_saved_voice_id()

        self.cmb_voices.blockSignals(True)
        self.cmb_voices.clear()
        target_idx = 0
        for idx, v in enumerate(voices):
            self.cmb_voices.addItem(v.display_name, v.id)
            if target_voice and v.id == target_voice:
                target_idx = idx

        if voices:
            self.cmb_voices.setCurrentIndex(target_idx)
        self.cmb_voices.blockSignals(False)

        self._on_voice_changed()

    def _filter_voices_by_search(self):
        self._populate_voices()

    def _on_voice_changed(self):
        voice_id = self.cmb_voices.currentData()
        if not voice_id:
            self.lbl_voice_info.setText("Chưa chọn giọng đọc.")
            return

        self._save_saved_voice_id(voice_id)

        vinfo = self.engine.find_voice(voice_id)
        if vinfo:
            status_str = "🟢 Đã cài đặt" if vinfo.is_available else "🔴 Chưa tải model"
            self.lbl_voice_info.setText(
                f"ID: {vinfo.id} | Engine: {vinfo.provider.upper()} | "
                f"Ngôn ngữ: {vinfo.language.upper()} | Trạng thái: {status_str}"
            )
            is_piper = vinfo.provider.lower() == "piper"
            self.btn_toggle_adv.setEnabled(is_piper)
            if not is_piper:
                self.btn_toggle_adv.setToolTip("Cài đặt nâng cao VITS chỉ áp dụng cho giọng Piper Offline.")
            else:
                self.btn_toggle_adv.setToolTip("Mở các tham số nâng cao của Piper VITS (noise_scale, noise_w, silence,...)")
        else:
            self.lbl_voice_info.setText(f"ID: {voice_id}")

    def _toggle_advanced_settings(self, checked: bool):
        self.widget_adv.setVisible(checked)
        self.btn_toggle_adv.setText("▼ Cài đặt nâng cao (Piper TTS)" if checked else "▶ Cài đặt nâng cao (Piper TTS)")

    def _toggle_custom_dsp(self, checked: bool):
        self.txt_custom_dsp.setVisible(checked)
        self.chk_warm_dsp.setEnabled(not checked)
        if checked:
            self.chk_warm_dsp.setToolTip("Đang bị vô hiệu hóa vì đã bật Custom FFmpeg Filter.")
        else:
            self.chk_warm_dsp.setToolTip("Áp dụng bộ lọc Studio Warm: tăng dải trầm 210Hz, triệt tiêu gai chói 3.4kHz && 6.2kHz, loại bỏ tiếng the thé kim loại.")

    def _on_noise_scale_changed(self, val):
        self.lbl_noise_scale_val.setText(f"{val / 100.0:.2f}")

    def _on_noise_w_changed(self, val):
        self.lbl_noise_w_val.setText(f"{val / 100.0:.2f}")

    def _on_length_scale_changed(self, val):
        self.lbl_length_scale_val.setText(f"{val / 100.0:.2f}x")

    def _on_silence_changed(self, val):
        self.lbl_silence_val.setText(f"{val / 100.0:.2f}s")

    def _apply_preset_warm(self):
        self.slider_noise_scale.setValue(33)
        self.slider_noise_w.setValue(50)
        self.slider_length_scale.setValue(108)
        self.slider_silence.setValue(25)
        self.chk_normalize.setChecked(True)
        self.chk_warm_dsp.setChecked(True)
        self.chk_custom_dsp.setChecked(False)

    def _apply_preset_clear(self):
        self.slider_noise_scale.setValue(35)
        self.slider_noise_w.setValue(45)
        self.slider_length_scale.setValue(105)
        self.slider_silence.setValue(25)
        self.chk_normalize.setChecked(True)
        self.chk_warm_dsp.setChecked(False)
        self.chk_custom_dsp.setChecked(False)

    def _apply_preset_default(self):
        self.slider_noise_scale.setValue(67)
        self.slider_noise_w.setValue(80)
        self.slider_length_scale.setValue(100)
        self.slider_silence.setValue(25)
        self.chk_normalize.setChecked(True)
        self.chk_warm_dsp.setChecked(False)
        self.chk_custom_dsp.setChecked(False)
        self.spin_speaker_id.setValue(0)

    def _get_piper_options(self) -> dict:
        return {
            "noise_scale": self.slider_noise_scale.value() / 100.0,
            "noise_w_scale": self.slider_noise_w.value() / 100.0,
            "length_scale": (self.slider_length_scale.value() / 100.0) if self.slider_length_scale.value() != 100 else None,
            "sentence_silence": self.slider_silence.value() / 100.0,
            "normalize_audio": self.chk_normalize.isChecked(),
            "warm_dsp": self.chk_warm_dsp.isChecked(),
            "use_custom_dsp": self.chk_custom_dsp.isChecked(),
            "custom_dsp": self.txt_custom_dsp.text().strip() if self.chk_custom_dsp.isChecked() else "",
            "speaker_id": self.spin_speaker_id.value() if self.spin_speaker_id.value() > 0 else None,
            "volume": 1.0,
        }

    def _on_speed_changed(self, val):
        speed_f = val / 100.0
        self.lbl_speed_val.setText(f"{speed_f:.2f}x")

    def _on_pitch_changed(self, val):
        sign = "+" if val > 0 else ""
        self.lbl_pitch_val.setText(f"{sign}{val}Hz")

    def _update_text_stats(self):
        txt = self.txt_input.toPlainText().strip()
        words = len(txt.split()) if txt else 0
        chars = len(txt)
        # Average reading speed ~ 4 words per second
        est_sec = round(words / 4.0, 1) if words else 0
        self.lbl_stats.setText(f"{words} từ | {chars} ký tự | Dự kiến: ~{est_sec}s")

    def _import_txt_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Chọn file văn bản", "", "Text Files (*.txt);;All Files (*.*)"
        )
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.txt_input.setPlainText(content)
            except Exception as e:
                QMessageBox.critical(self, "Lỗi đọc file", f"Không thể nạp file:\n{e}")

    def _preview_normalized_text(self):
        raw_text = self.txt_input.toPlainText().strip()
        if not raw_text:
            QMessageBox.information(self, "Thông báo", "Vui lòng nhập văn bản trước khi chuẩn hóa.")
            return

        norm_text = self.engine.normalize_text(raw_text, provider="piper", language="vi")
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Xem trước chuẩn hóa tiếng Việt")
        dialog.setText("Văn bản sau khi chuẩn hóa phiên âm:")
        dialog.setInformativeText(norm_text)
        dialog.setStandardButtons(QMessageBox.Ok | QMessageBox.Apply)
        dialog.button(QMessageBox.Apply).setText("Áp dụng vào ô nhập")
        ret = dialog.exec()
        if ret == QMessageBox.Apply:
            self.txt_input.setPlainText(norm_text)

    def _get_output_dir(self) -> Path:
        out_dir = Path(__file__).resolve().parent / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    def _open_output_directory(self):
        out_dir = self._get_output_dir()
        if sys.platform == "win32":
            os.startfile(str(out_dir))
        else:
            subprocess.run(["xdg-open", str(out_dir)])

    def _open_voice_manager(self):
        from .ui_voice_manager import VoiceManagerDialog
        dlg = VoiceManagerDialog(self)
        dlg.voices_changed.connect(self._on_voices_updated)
        dlg.exec()
        self._on_voices_updated()

    def _on_voices_updated(self):
        self.engine._load_voices()
        self._populate_voices()

    def _start_synthesis(self):
        text = self.txt_input.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Thiếu dữ liệu", "Vui lòng nhập nội dung cần đọc.")
            return

        voice_id = self.cmb_voices.currentData()
        if not voice_id:
            QMessageBox.warning(self, "Thiếu dữ liệu", "Vui lòng chọn một giọng đọc.")
            return

        speed = self.slider_speed.value() / 100.0
        pitch = self.slider_pitch.value()
        fmt = "wav" if self.cmb_format.currentIndex() == 0 else "mp3"
        piper_opts = self._get_piper_options()

        # Prepare output path
        out_dir = self._get_output_dir()
        file_name = f"tts_output_{QTime.currentTime().toString('hhmmss')}.{fmt}"
        target_path = str(out_dir / file_name)

        # UI state
        self.btn_synthesize.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.lbl_status.setText("Đang khởi tạo tổng hợp âm thanh...")

        # Worker
        self.worker = SynthesisWorker(
            engine=self.engine,
            text=text,
            output_path=target_path,
            voice_id=voice_id,
            speed=speed,
            pitch=pitch,
            output_format=fmt,
            piper_options=piper_opts,
        )
        self.worker.progress_signal.connect(self._on_synth_progress)
        self.worker.finished_signal.connect(self._on_synth_finished)
        self.worker.error_signal.connect(self._on_synth_error)
        self.worker.start()

    def _on_synth_progress(self, msg: str):
        self.lbl_status.setText(msg)

    def _on_synth_finished(self, result: dict):
        self.btn_synthesize.setEnabled(True)
        self.progress_bar.setVisible(False)

        self.current_audio_path = result.get("file_path")
        duration = result.get("duration_sec", 0.0)
        size_kb = result.get("file_size_bytes", 0) / 1024.0
        sample_rate = result.get("sample_rate", 22050)
        sr_str = f"{sample_rate / 1000.0:.1f}kHz" if sample_rate else "22.05kHz"

        self.lbl_status.setText(
            f"✅ Hoàn tất! Thời lượng: {duration:.1f}s | Tần số: {sr_str} | Dung lượng: {size_kb:.1f} KB | {os.path.basename(self.current_audio_path)}"
        )

        # Load into player
        if self.current_audio_path and os.path.exists(self.current_audio_path):
            self.media_player.setSource(QUrl.fromLocalFile(self.current_audio_path))
            self.btn_play_pause.setEnabled(True)
            self.btn_stop.setEnabled(True)
            self.btn_save_as.setEnabled(True)
            self.btn_open_file.setEnabled(True)
            # Auto play
            self.media_player.play()

    def _on_synth_error(self, err_msg: str):
        self.btn_synthesize.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.lbl_status.setText("❌ Lỗi khi tổng hợp âm thanh.")
        QMessageBox.critical(self, "Lỗi tổng hợp", f"Đã xảy ra lỗi:\n{err_msg}")

    # Audio Player Handlers
    def _toggle_playback(self):
        state = self.media_player.playbackState()
        if state == QMediaPlayer.PlayingState:
            self.media_player.pause()
        else:
            self.media_player.play()

    def _stop_playback(self):
        self.media_player.stop()

    def _on_player_state_changed(self, state):
        if state == QMediaPlayer.PlayingState:
            self.btn_play_pause.setText("⏸ Tạm dừng")
        else:
            self.btn_play_pause.setText("▶ Phát")

    def _on_player_position_changed(self, pos_ms):
        dur_ms = self.media_player.duration()
        if dur_ms > 0:
            val = int((pos_ms / dur_ms) * 1000)
            self.slider_timeline.blockSignals(True)
            self.slider_timeline.setValue(val)
            self.slider_timeline.blockSignals(False)

        self.lbl_curr_time.setText(self._format_time(pos_ms))

    def _on_player_duration_changed(self, dur_ms):
        self.lbl_total_time.setText(self._format_time(dur_ms))

    def _on_seek_timeline(self, val):
        dur_ms = self.media_player.duration()
        if dur_ms > 0:
            target_ms = int((val / 1000.0) * dur_ms)
            self.media_player.setPosition(target_ms)

    def _on_volume_changed(self, val):
        self.audio_output.setVolume(val / 100.0)

    def _format_time(self, ms: int) -> str:
        s = int(ms / 1000)
        m = int(s / 60)
        s = s % 60
        return f"{m:02d}:{s:02d}"

    def _save_audio_as(self):
        if not self.current_audio_path or not os.path.exists(self.current_audio_path):
            return

        ext = os.path.splitext(self.current_audio_path)[1].lower()
        filter_str = "WAV Audio (*.wav)" if ext == ".wav" else "MP3 Audio (*.mp3)"
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Lưu file âm thanh", os.path.basename(self.current_audio_path), filter_str
        )
        if save_path:
            import shutil

            try:
                shutil.copy2(self.current_audio_path, save_path)
                QMessageBox.information(self, "Thành công", f"Đã lưu file thành công tại:\n{save_path}")
            except Exception as e:
                QMessageBox.critical(self, "Lỗi lưu file", f"Không thể lưu file:\n{e}")

    def _open_current_audio_file(self):
        if self.current_audio_path and os.path.exists(self.current_audio_path):
            if sys.platform == "win32":
                subprocess.run(f'explorer /select,"{os.path.abspath(self.current_audio_path)}"')
            else:
                subprocess.run(["xdg-open", self.current_audio_path])
