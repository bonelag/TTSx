import asyncio
import json
import os
import re
import shutil
import subprocess
import threading
import time
import wave
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from .runtime_paths import app_path, bin_path, bundle_root, models_path, temp_path, subprocess_text_kwargs

_PIPER_VOICE_CACHE: Dict[str, object] = {}
_PIPER_VOICE_CACHE_LOCK = threading.Lock()
_VIETNAMESE_NORMALIZER = None


def _resolve_piper_model_path(provider_voice: str) -> str:
    raw = str(provider_voice or "").strip().replace("/", os.sep)
    if not raw:
        return ""
    normalized = os.path.normpath(raw)
    if os.path.isabs(normalized) and os.path.exists(normalized):
        return normalized
    
    # Check within TTS-App models directory
    cand1 = os.path.join(bundle_root(), normalized)
    if os.path.exists(cand1):
        return cand1
    cand2 = models_path(normalized)
    if os.path.exists(cand2):
        return cand2
    
    # Strip prefix if specified as models/piper/...
    if normalized.startswith(f"models{os.sep}"):
        rel = normalized[len(f"models{os.sep}"):]
        cand3 = models_path(rel)
        if os.path.exists(cand3):
            return cand3
    else:
        cand4 = models_path("piper", normalized)
        if os.path.exists(cand4):
            return cand4
        cand5 = models_path("piper-en", normalized)
        if os.path.exists(cand5):
            return cand5

    cand_model = models_path("model", "piper", normalized)
    if os.path.exists(cand_model):
        return cand_model

    filename = os.path.basename(normalized)
    for sub in [
        ("piper", filename),
        ("piper-en", filename),
        ("model", "piper", "vi", filename),
        ("model", "piper", "en", filename),
        ("model", "piper", "id", filename),
    ]:
        cand_sub = models_path(*sub)
        if os.path.exists(cand_sub):
            return cand_sub

    return cand1


def _get_cached_piper_voice(*, model_path: str, on_progress: Optional[Callable[[str], None]] = None):
    try:
        from piper.voice import PiperVoice
    except ImportError:
        raise ImportError("Thư viện piper-tts chưa được cài đặt. Vui lòng chạy: pip install piper-tts")

    model_key = os.path.abspath(str(model_path or "").strip())
    if not model_key or not os.path.exists(model_key):
        raise ValueError(f"Không tìm thấy file mô hình Piper: {model_path}")

    # Ensure config json exists
    config_path = f"{model_key}.json"
    if not os.path.exists(config_path):
        stem_json = f"{os.path.splitext(model_key)[0]}.json"
        if os.path.exists(stem_json):
            config_path = stem_json
        else:
            # Check for config.json in model folder
            dir_config = os.path.join(os.path.dirname(model_key), "config.json")
            if os.path.exists(dir_config):
                try:
                    shutil.copy(dir_config, config_path)
                except Exception:
                    pass
            else:
                # Find any existing *.onnx.json template in the folder
                import glob
                templates = glob.glob(os.path.join(os.path.dirname(model_key), "*.onnx.json"))
                if templates:
                    try:
                        shutil.copy(templates[0], config_path)
                    except Exception:
                        pass

    with _PIPER_VOICE_CACHE_LOCK:
        cached = _PIPER_VOICE_CACHE.get(model_key)
        if cached is not None:
            return cached

    if on_progress:
        on_progress(f"Đang nạp mô hình Piper: {os.path.basename(model_key)}...")

    voice = PiperVoice.load(model_key, config_path=config_path if os.path.exists(config_path) else None)

    with _PIPER_VOICE_CACHE_LOCK:
        _PIPER_VOICE_CACHE[model_key] = voice
        return voice


def _ffmpeg_path() -> str:
    local_ffmpeg = bin_path("ffmpeg", "ffmpeg.exe")
    if os.path.exists(local_ffmpeg):
        return local_ffmpeg
    local_ffmpeg_bin = bin_path("ffmpeg.exe")
    if os.path.exists(local_ffmpeg_bin):
        return local_ffmpeg_bin
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    return "ffmpeg"


def _validate_generated_wav(wav_path: str) -> None:
    if not wav_path or not os.path.exists(wav_path):
        raise RuntimeError("File WAV không tồn tại sau khi tổng hợp.")
    if os.path.getsize(wav_path) <= 44:
        raise RuntimeError("File WAV rỗng hoặc không có dữ liệu âm thanh.")
    try:
        with wave.open(wav_path, "rb") as wav_file:
            channels = int(wav_file.getnchannels() or 0)
            frame_rate = int(wav_file.getframerate() or 0)
            frame_count = int(wav_file.getnframes() or 0)
        if channels <= 0:
            raise RuntimeError("File WAV không có kênh âm thanh hợp lệ.")
        if frame_rate <= 0 or frame_count <= 0:
            raise RuntimeError("File WAV không chứa dữ liệu âm thanh.")
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"File WAV không hợp lệ: {exc}") from exc


def _speed_to_float(speed) -> float:
    if isinstance(speed, (int, float)):
        return float(speed)
    text = str(speed or "").strip().lower().replace("x", "")
    try:
        return float(text or "1.0")
    except ValueError:
        return 1.0


# ---------------------------------------------------------------------------
# TTSx phonemizer tiếng Việt — Python thuần (app/ttsx_phonemizer.py)
# ---------------------------------------------------------------------------

_TTSX_PHONEMIZER_AVAILABLE: Optional[bool] = None


def _ttsx_phonemize_available() -> bool:
    """Kiểm tra module ttsx_phonemizer + espeakng-loader dùng được không (cache)."""
    global _TTSX_PHONEMIZER_AVAILABLE
    if _TTSX_PHONEMIZER_AVAILABLE is not None:
        return _TTSX_PHONEMIZER_AVAILABLE
    try:
        from .ttsx_phonemizer import ttsx_phonemize  # noqa: F401
        import espeakng_loader  # noqa: F401

        _TTSX_PHONEMIZER_AVAILABLE = True
    except Exception:
        _TTSX_PHONEMIZER_AVAILABLE = False
    return _TTSX_PHONEMIZER_AVAILABLE


def _ttsx_phonemize_pipeline(text: str) -> Optional[list]:
    """Chạy pipeline text TTSx (chuẩn hóa + tách câu + phonemize espeak-ng IPA).
    Trả về list chuỗi phoneme (mỗi câu 1 phần tử), hoặc None nếu lỗi
    (caller fallback về pipeline piper espeak).
    """
    if not _ttsx_phonemize_available():
        return None
    try:
        from .ttsx_phonemizer import ttsx_phonemize

        phonemes = ttsx_phonemize(text)
        if phonemes:
            return phonemes
    except Exception:
        pass
    return None


def _ttsx_ids_from_phonemes(voice, phoneme_str: str) -> list:
    """Phoneme string -> ID sequence (BOS, PAD + phoneme+PAD*, EOS)."""
    from .ttsx_phonemizer import phonemes_to_ids

    return phonemes_to_ids(phoneme_str, voice.config.phoneme_id_map)


def _optimize_punctuation_and_capitalization(text: str) -> str:
    """Optimize punctuation rhythm and capitalize sentence beginnings to ensure Piper espeak-ng recognizes sentence boundaries."""
    if not text:
        return ""
    import re
    t = str(text)

    # 1. Transform internal pause marks
    t = re.sub(r"\.{3,}", ", , ", t)       # Ellipsis (...) -> deep breath pause
    t = re.sub(r"\s*;\s*", ", ", t)        # Semicolons (;) -> clause pause
    t = re.sub(r"\s*:\s*", ", ", t)        # Colons (:) -> clause pause
    t = re.sub(r"\s*[-–—]\s*", ", ", t)    # Dashes -> clause pause

    # 2. Normalize whitespace around punctuation
    t = re.sub(r"\s*,\s*", ", ", t)
    t = re.sub(r"\s*\.\s*", ". ", t)
    t = re.sub(r"\s*!\s*", "! ", t)
    t = re.sub(r"\s*\?\s*", "? ", t)
    t = " ".join(t.split()).strip()

    # 3. Capitalize first letter of every sentence so Piper / espeak-ng detects sentence boundaries
    if t:
        t = t[0].upper() + t[1:]
    vn_chars = "a-zàáảãạăắằẳẵặâấầẩẫậđèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵ"
    t = re.sub(
        rf"([.!?\n]\s*)([{vn_chars}])",
        lambda m: m.group(1) + m.group(2).upper(),
        t,
    )
    return t


def normalize_text_for_tts(text: str, *, provider: str = "piper", language: str = "vi") -> str:
    value = " ".join(str(text or "").replace("\n", " ").split()).strip()
    if not value:
        return ""
    if str(provider or "").strip().lower() != "piper":
        return value
    if not str(language or "vi").strip().lower().startswith("vi"):
        return _optimize_punctuation_and_capitalization(value)

    value = _optimize_punctuation_and_capitalization(value)

    global _VIETNAMESE_NORMALIZER
    if _VIETNAMESE_NORMALIZER is None:
        try:
            from vietnormalizer.normalizer import VietnameseNormalizer
            from vietnormalizer import normalizer as vn_mod
            import csv

            custom_dir = Path(models_path("vietnormalizer"))
            combined_dir = custom_dir / "_combined"
            default_data = Path(vn_mod.__file__).parent / "data"

            if custom_dir.exists() and any(custom_dir.glob("*.csv")):
                combined_dir.mkdir(parents=True, exist_ok=True)
                dict_files = [
                    ("acronyms.csv", "acronym"),
                    ("non-vietnamese-words.csv", "original"),
                ]
                for filename, key_col in dict_files:
                    merged = {}
                    default_file = default_data / filename
                    if default_file.exists():
                        with open(default_file, "r", encoding="utf-8") as f:
                            for row in csv.DictReader(f):
                                if key_col in row:
                                    merged[row[key_col]] = row
                    custom_file = custom_dir / filename
                    if custom_file.exists():
                        with open(custom_file, "r", encoding="utf-8") as f:
                            for row in csv.DictReader(f):
                                if key_col in row:
                                    merged[row[key_col]] = row
                    out_file = combined_dir / filename
                    if merged:
                        with open(out_file, "w", encoding="utf-8", newline="") as f:
                            writer = csv.DictWriter(f, fieldnames=list(next(iter(merged.values())).keys()))
                            writer.writeheader()
                            writer.writerows(merged.values())

                _VIETNAMESE_NORMALIZER = VietnameseNormalizer(data_dir=str(combined_dir))
            else:
                _VIETNAMESE_NORMALIZER = VietnameseNormalizer()
        except Exception:
            _VIETNAMESE_NORMALIZER = False

    if _VIETNAMESE_NORMALIZER:
        try:
            if hasattr(_VIETNAMESE_NORMALIZER, "normalize"):
                norm = _VIETNAMESE_NORMALIZER.normalize(value)
                return _optimize_punctuation_and_capitalization(norm)
            elif callable(_VIETNAMESE_NORMALIZER):
                norm = _VIETNAMESE_NORMALIZER(value)
                return _optimize_punctuation_and_capitalization(norm)
        except Exception:
            return _optimize_punctuation_and_capitalization(value)

    return _optimize_punctuation_and_capitalization(value)


def _normalize_ffmpeg_filter(filter_str: str) -> str:
    """Auto-normalizes common user aliases, typos, and channel parameters in FFmpeg filter strings."""
    if not filter_str or not isinstance(filter_str, str):
        return ""

    s = filter_str.strip().strip("'\"")

    # 1. Fix apulsator parameter aliases: offset -> offset_l & offset_r, freq -> hz
    def fix_apulsator(match):
        inner = match.group(1) or ""
        inner = re.sub(r'(?<![a-zA-Z0-9_])offset=([0-9.]+)', r'offset_l=\1:offset_r=\1', inner)
        inner = re.sub(r'(?<![a-zA-Z0-9_])(?:freq|frequency)=([0-9.]+)', r'hz=\1', inner)
        return f"apulsator={inner}" if inner else "apulsator"

    s = re.sub(r'\bapulsator(?:=([a-zA-Z0-9_:=.\-]+))?', fix_apulsator, s)

    # 2. Fix equalizer long-form parameter names: frequency -> f, gain -> g, width -> w, type -> t
    def fix_equalizer(match):
        inner = match.group(1) or ""
        inner = re.sub(r'(?<![a-zA-Z0-9_])frequency=([0-9.]+)', r'f=\1', inner)
        inner = re.sub(r'(?<![a-zA-Z0-9_])gain=([\-0-9.]+)', r'g=\1', inner)
        inner = re.sub(r'(?<![a-zA-Z0-9_])width=([0-9.]+)', r'w=\1', inner)
        inner = re.sub(r'(?<![a-zA-Z0-9_])type=([a-zA-Z0-9]+)', r't=\1', inner)
        return f"equalizer={inner}"

    s = re.sub(r'\bequalizer=([a-zA-Z0-9_:=.\-]+)', fix_equalizer, s)

    # 3. Fix pass filters: lowpass/highpass/bandpass frequency -> f
    def fix_pass(match):
        filter_name = match.group(1)
        inner = match.group(2) or ""
        inner = re.sub(r'(?<![a-zA-Z0-9_])(?:freq|frequency)=([0-9.]+)', r'f=\1', inner)
        inner = re.sub(r'(?<![a-zA-Z0-9_])width=([0-9.]+)', r'w=\1', inner)
        return f"{filter_name}={inner}"

    s = re.sub(r'\b(lowpass|highpass|bandpass|allpass)=([a-zA-Z0-9_:=.\-]+)', fix_pass, s)

    # Clean whitespace and redundant commas
    s = re.sub(r'\s*,\s*', ',', s)
    s = re.sub(r',+', ',', s)
    return s.strip(',')


def piper_tts_to_wav(
    *,
    text: str,
    output_wav: str,
    provider_voice: str,
    speed: float = 1.0,
    pitch: int = 0,
    language: str = "vi",
    piper_options: Optional[dict] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> str:
    from piper.config import SynthesisConfig

    model_path = _resolve_piper_model_path(provider_voice)
    if not model_path or not os.path.exists(model_path):
        raise ValueError(f"Không tìm thấy file mô hình Piper tại: {provider_voice}")

    voice = _get_cached_piper_voice(model_path=model_path, on_progress=on_progress)
    norm_text = normalize_text_for_tts(text, provider="piper", language=language)

    if on_progress:
        on_progress("Đang tổng hợp giọng nói qua Piper TTS...")

    out_path = Path(output_wav)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_wav = str(out_path.with_name(f"{out_path.stem}_raw{out_path.suffix}"))

    speed_val = max(0.5, min(3.0, _speed_to_float(speed)))
    opts = piper_options or {}

    length_scale_opt = opts.get("length_scale")
    if length_scale_opt is not None:
        eff_length_scale = float(length_scale_opt)
    else:
        eff_length_scale = 1.0 / speed_val

    noise_scale_opt = opts.get("noise_scale")
    noise_w_opt = opts.get("noise_w_scale")
    # Chuẩn hóa biên độ: KHÔNG đẩy peak từng câu lên 1.0
    # (normalize_audio của piper amplify +4~5dB làm giọng chói);
    # thay vào đó chỉ attenuate nếu đỉnh vượt ngưỡng, giữ nguyên dynamics gốc.
    normalize_audio = opts.get("normalize_audio", False)
    peak_ceiling = float(opts.get("peak_ceiling", 0.99) or 0.99)
    volume_opt = float(opts.get("volume", 1.0) or 1.0)
    speaker_id_opt = opts.get("speaker_id")
    silence_sec = float(opts.get("sentence_silence", 0.0) or 0.0)

    syn_config = SynthesisConfig(
        speaker_id=speaker_id_opt,
        length_scale=eff_length_scale,
        noise_scale=float(noise_scale_opt) if noise_scale_opt is not None else None,
        noise_w_scale=float(noise_w_opt) if noise_w_opt is not None else None,
        normalize_audio=normalize_audio,
        volume=volume_opt,
    )

    # Ghép audio từng câu; áp peak ceiling (chỉ attenuate, không amplify)
    import numpy as np

    audio_chunks: list = []
    sample_rate = 22050
    sample_width = 2
    sample_channels = 1

    # Đường phonemize TTSx (espeak-ng IPA + tone digit 1-7) cho tiếng Việt
    use_ttsx_phon = (
        bool(opts.get("use_ttsx_phonemizer", True))
        and str(language or "").lower().startswith("vi")
        and _ttsx_phonemize_available()
    )
    ttsx_sentences = None
    if use_ttsx_phon:
        if on_progress:
            on_progress("Đang xử lý văn bản + phonemize tiếng Việt...")
        # Toàn bộ text pipeline TTSx (số->chữ, lowercase, từ viết tắt, phiên âm,
        # tách câu, phonemize espeak-ng IPA + tone digit)
        ttsx_sentences = _ttsx_phonemize_pipeline(text)

    if ttsx_sentences:
        for phoneme_str in ttsx_sentences:
            if not phoneme_str:
                continue
            ids = _ttsx_ids_from_phonemes(voice, phoneme_str)
            audio = np.asarray(
                voice.phoneme_ids_to_audio(ids, syn_config), dtype=np.float32
            )
            audio_chunks.append(audio)
            if silence_sec > 0:
                audio_chunks.append(
                    np.zeros(int(sample_rate * silence_sec), dtype=np.float32)
                )
        sample_rate = voice.config.sample_rate
    else:
        for audio_chunk in voice.synthesize(norm_text, syn_config=syn_config):
            sample_rate = audio_chunk.sample_rate
            sample_width = audio_chunk.sample_width
            sample_channels = audio_chunk.sample_channels
            audio_chunks.append(
                np.frombuffer(audio_chunk.audio_int16_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            )
            if silence_sec > 0:
                silence_frames = int(audio_chunk.sample_rate * silence_sec)
                audio_chunks.append(
                    np.zeros(silence_frames * audio_chunk.sample_channels, dtype=np.float32)
                )

    if not audio_chunks:
        raise RuntimeError("Piper không sinh được dữ liệu âm thanh.")

    merged_audio = np.concatenate(audio_chunks) if len(audio_chunks) > 1 else audio_chunks[0]

    # Peak ceiling (soft-limit): chỉ hạ nếu vượt ngưỡng — giữ nguyên loudness gốc của model
    peak_val = float(np.max(np.abs(merged_audio))) if merged_audio.size else 0.0
    if peak_val > peak_ceiling and peak_val > 1e-8:
        merged_audio = merged_audio * (peak_ceiling / peak_val)

    pcm16 = np.clip(merged_audio, -1.0, 1.0)
    pcm16 = (pcm16 * 32767.0).astype(np.int16)

    with wave.open(temp_wav, "wb") as wav_file:
        wav_file.setframerate(sample_rate)
        wav_file.setsampwidth(sample_width)
        wav_file.setnchannels(sample_channels)
        wav_file.writeframes(pcm16.tobytes())

    _validate_generated_wav(temp_wav)

    # Apply Pitch shift via FFmpeg if pitch != 0
    pitch_int = int(round(float(pitch or 0)))
    if pitch_int != 0:
        if on_progress:
            on_progress("Đang tinh chỉnh cao độ âm thanh (Pitch)...")
        factor = max(0.5, min(2.0, 1.0 + (pitch_int / 100.0)))
        pitch_wav = str(out_path.with_name(f"{out_path.stem}_pitch{out_path.suffix}"))
        ffmpeg = _ffmpeg_path()
        sample_rate = 22050
        try:
            with wave.open(temp_wav, "rb") as wf:
                sample_rate = wf.getframerate()
        except Exception:
            pass
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            temp_wav,
            "-af",
            f"asetrate={sample_rate}*{factor:.4f},aresample={sample_rate},atempo=1/{factor:.4f}",
            pitch_wav,
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **subprocess_text_kwargs())
        if os.path.exists(temp_wav):
            try:
                os.remove(temp_wav)
            except OSError:
                pass
        temp_wav = pitch_wav

    # Apply DSP Audio Mastering (Custom FFmpeg filter strictly overrides warm_dsp)
    use_custom_dsp = bool(opts.get("use_custom_dsp", False))
    custom_dsp = _normalize_ffmpeg_filter(str(opts.get("custom_dsp", "") or "").strip())
    warm_dsp = bool(opts.get("warm_dsp", False))

    dsp_filter = None
    if use_custom_dsp:
        # Strictly follow custom filter string; if empty, do not apply any DSP filter
        if custom_dsp:
            dsp_filter = custom_dsp
    elif warm_dsp:
        # Open Studio Natural DSP (Default Mastering Filter)
        # Gentle warmth @ 200Hz (+2.2dB), De-mud cut @ 420Hz (-3.8dB), De-harsh @ 3.4kHz (-3.6dB) & 6.2kHz (-3.5dB), Air space @ 11kHz (+1.2dB)
        dsp_filter = "volume=0.92,equalizer=f=200:t=q:w=1.2:g=2.2,equalizer=f=420:t=q:w=1.6:g=-3.8,equalizer=f=3400:t=q:w=2.2:g=-3.6,equalizer=f=6200:t=q:w=2.5:g=-3.5,equalizer=f=11000:t=q:w=1.5:g=1.2"

    if dsp_filter:
        if on_progress:
            on_progress("Đang áp dụng bộ lọc âm thanh FFmpeg DSP...")
        dsp_wav = str(out_path.with_name(f"{out_path.stem}_dsp{out_path.suffix}"))
        ffmpeg = _ffmpeg_path()
        cmd = [ffmpeg, "-y", "-i", temp_wav, "-af", dsp_filter, dsp_wav]
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **subprocess_text_kwargs()
        )
        if proc.returncode != 0:
            err_lines = [
                line.strip()
                for line in (proc.stderr or "").splitlines()
                if line.strip()
                and not line.startswith("ffmpeg version")
                and not line.startswith("built with")
                and not line.startswith("configuration:")
                and not line.startswith("lib")
            ]
            err_msg = "\n".join(err_lines[-3:]) if err_lines else f"Exit code {proc.returncode}"
            if os.path.exists(dsp_wav):
                try:
                    os.remove(dsp_wav)
                except OSError:
                    pass
            raise RuntimeError(f"Lỗi tham số bộ lọc FFmpeg (Filter Syntax Error):\n{err_msg}")

        if os.path.exists(temp_wav):
            try:
                os.remove(temp_wav)
            except OSError:
                pass
        temp_wav = dsp_wav

    if os.path.exists(output_wav):
        try:
            os.remove(output_wav)
        except OSError:
            pass
    shutil.move(temp_wav, output_wav)
    _validate_generated_wav(output_wav)
    return output_wav


def edge_tts_to_wav(
    *,
    text: str,
    output_wav: str,
    provider_voice: str,
    speed: float = 1.0,
    pitch: int = 0,
    language: str = "vi",
    on_progress: Optional[Callable[[str], None]] = None,
) -> str:
    try:
        import edge_tts
    except ImportError:
        raise ImportError("Thư viện edge-tts chưa được cài đặt. Vui lòng chạy: pip install edge-tts")

    voice_id = (provider_voice or "").strip()
    if not voice_id:
        voice_id = "vi-VN-HoaiMyNeural" if str(language).startswith("vi") else "en-US-JennyNeural"

    norm_text = normalize_text_for_tts(text, provider="edge", language=language)
    speed_float = _speed_to_float(speed)
    speed_pct = int(round((speed_float - 1.0) * 100))
    rate_str = f"+{speed_pct}%" if speed_pct >= 0 else f"{speed_pct}%"

    pitch_int = int(round(float(pitch or 0)))
    pitch_str = f"+{pitch_int}Hz" if pitch_int >= 0 else f"{pitch_int}Hz"

    out_path = Path(output_wav)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_mp3 = str(out_path.with_name(f"{out_path.stem}_edge.mp3"))

    if on_progress:
        on_progress(f"Đang kết nối Edge TTS ({voice_id})...")

    async def _run_edge():
        communicate = edge_tts.Communicate(norm_text, voice=voice_id, rate=rate_str, pitch=pitch_str)
        await communicate.save(temp_mp3)

    try:
        asyncio.run(_run_edge())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run_edge())
        loop.close()

    # Convert MP3 to WAV using ffmpeg
    ffmpeg = _ffmpeg_path()
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        temp_mp3,
        "-vn",
        output_wav,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **subprocess_text_kwargs())

    if os.path.exists(temp_mp3):
        try:
            os.remove(temp_mp3)
        except OSError:
            pass

    _validate_generated_wav(output_wav)
    return output_wav


def synthesize_text_to_audio(
    *,
    text: str,
    output_path: str,
    provider: str,
    provider_voice: str,
    speed: float = 1.0,
    pitch: int = 0,
    language: str = "vi",
    piper_options: Optional[dict] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> str:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    is_mp3 = target.suffix.lower() == ".mp3"

    wav_target = str(target.with_suffix(".wav")) if is_mp3 else output_path

    prov = str(provider or "piper").strip().lower()
    if prov == "piper":
        piper_tts_to_wav(
            text=text,
            output_wav=wav_target,
            provider_voice=provider_voice,
            speed=speed,
            pitch=pitch,
            language=language,
            piper_options=piper_options,
            on_progress=on_progress,
        )
    elif prov in ("edge", "edge-tts"):
        edge_tts_to_wav(
            text=text,
            output_wav=wav_target,
            provider_voice=provider_voice,
            speed=speed,
            pitch=pitch,
            language=language,
            on_progress=on_progress,
        )
    else:
        raise ValueError(f"Provider TTS không được hỗ trợ: {provider}")

    # Convert to MP3 if requested
    if is_mp3:
        if on_progress:
            on_progress("Đang xuất file MP3 qua FFmpeg...")
        ffmpeg = _ffmpeg_path()
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            wav_target,
            "-vn",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "192k",
            output_path,
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **subprocess_text_kwargs())
        if os.path.exists(wav_target) and wav_target != output_path:
            try:
                os.remove(wav_target)
            except OSError:
                pass

    return output_path
