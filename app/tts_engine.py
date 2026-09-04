import json
import os
import sys
import wave
from pathlib import Path
from typing import Callable, Dict, List, Optional

# Local imports from TTS-App
from .runtime_paths import app_path, bin_path, bundle_root, models_path, temp_path
from .tts_processor import (
    normalize_text_for_tts,
    synthesize_text_to_audio,
    _resolve_piper_model_path,
    _ffmpeg_path,
    _speed_to_float,
    _validate_generated_wav,
)


class VoiceInfo:
    def __init__(
        self,
        voice_id: str,
        name: str,
        provider: str,
        provider_voice: str,
        language: str = "vi",
        gender: str = "female",
        is_available: bool = True,
        status_note: str = "",
    ):
        self.id = voice_id
        self.name = name
        self.provider = provider.lower()
        self.provider_voice = provider_voice
        self.language = language
        self.gender = gender.lower()
        self.is_available = is_available
        self.status_note = status_note

    @property
    def display_name(self) -> str:
        provider_label = "Piper Offline" if self.provider == "piper" else "Edge Online"
        gender_label = "Nữ" if self.gender == "female" else ("Nam" if self.gender == "male" else self.gender.capitalize())
        lang_label = "VI" if self.language.startswith("vi") else ("EN" if self.language.startswith("en") else self.language.upper())
        status = "" if self.is_available else " [Chưa tải]"
        return f"{self.name} ({lang_label} - {gender_label} - {provider_label}){status}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "provider_voice": self.provider_voice,
            "language": self.language,
            "gender": self.gender,
            "display_name": self.display_name,
            "is_available": self.is_available,
        }


class TTSEngine:
    def __init__(self):
        self._voices: List[VoiceInfo] = []
        self._load_voices()

    def _load_voices(self):
        """Load and merge voices from local voice catalogs and scan models folder."""
        self._voices = []
        seen_ids = set()

        catalogs = [
            models_path("model", "piper", "voice.json"),
            models_path("piper", "voice.json"),
            models_path("model", "piper", "voices.json"),
            models_path("piper", "voices.json"),
            models_path("piper-en", "voices.json"),
            app_path("voice_catalog.json"),
        ]

        for cat_file in catalogs:
            if not os.path.exists(cat_file):
                continue
            try:
                with open(cat_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    voices = data.get("voices", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                    for v in voices:
                        vid = v.get("id")
                        if not vid or vid in seen_ids:
                            continue
                        seen_ids.add(vid)

                        provider = v.get("provider", "piper").strip().lower()
                        provider_voice = v.get("provider_voice", "")
                        language = v.get("language", "vi")
                        gender = v.get("gender", "female")
                        name = v.get("name", vid)

                        is_available = True
                        status_note = ""
                        if provider == "piper":
                            resolved_path = _resolve_piper_model_path(provider_voice)
                            if not os.path.exists(resolved_path):
                                is_available = False
                                status_note = "Model chưa tải"

                        self._voices.append(
                            VoiceInfo(
                                voice_id=vid,
                                name=name,
                                provider=provider,
                                provider_voice=provider_voice,
                                language=language,
                                gender=gender,
                                is_available=is_available,
                                status_note=status_note,
                            )
                        )
            except Exception as e:
                print(f"[!] Warning reading voice catalog {cat_file}: {e}")

        # Add Edge-TTS online voices if not already added
        edge_voices_list = [
            ("edge-vi-hoaimy", "Hoài My (Edge Neural)", "vi-VN-HoaiMyNeural", "vi", "female"),
            ("edge-vi-namminh", "Nam Minh (Edge Neural)", "vi-VN-NamMinhNeural", "vi", "male"),
            ("edge-en-jenny", "Jenny (Edge Neural)", "en-US-JennyNeural", "en", "female"),
            ("edge-en-guy", "Guy (Edge Neural)", "en-US-GuyNeural", "en", "male"),
        ]
        for vid, vname, pvoice, vlang, vgender in edge_voices_list:
            if vid not in seen_ids:
                seen_ids.add(vid)
                self._voices.append(
                    VoiceInfo(
                        voice_id=vid,
                        name=vname,
                        provider="edge",
                        provider_voice=pvoice,
                        language=vlang,
                        gender=vgender,
                        is_available=True,
                        status_note="Online",
                    )
                )

        # Scan models/piper for any uncataloged .onnx files
        self._scan_local_piper_models(seen_ids)

    def _scan_local_piper_models(self, seen_ids: set):
        """Scan models/piper and models/piper-en for extra .onnx files."""
        search_dirs = [
            (models_path("piper"), "vi"),
            (models_path("piper-en"), "en"),
            (models_path("model", "piper", "vi"), "vi"),
            (models_path("model", "piper", "en"), "en"),
            (models_path("model", "piper", "id"), "id"),
            (models_path(), "vi"),
        ]

        for s_dir, lang in search_dirs:
            if not os.path.exists(s_dir):
                continue
            for file in os.listdir(s_dir):
                if file.endswith(".onnx"):
                    stem = Path(file).stem
                    if stem in seen_ids:
                        continue
                    seen_ids.add(stem)
                    rel_voice = f"models/piper/{file}" if lang == "vi" else f"models/piper-en/{file}"
                    pretty_name = stem.replace("_", " ").replace("-", " ").capitalize()
                    if "44k" in stem:
                        pretty_name += " (44.1kHz Hi-Fi)"
                    
                    self._voices.append(
                        VoiceInfo(
                            voice_id=stem,
                            name=pretty_name,
                            provider="piper",
                            provider_voice=rel_voice,
                            language=lang,
                            gender="female" if "n" in stem.lower() else "male",
                            is_available=True,
                            status_note="Tự động phát hiện",
                        )
                    )

    def get_voices(
        self,
        provider: Optional[str] = None,
        language: Optional[str] = None,
        provider_filter: Optional[str] = None,
        lang_filter: Optional[str] = None,
        available_only: bool = False,
    ) -> List[VoiceInfo]:
        prov = provider or provider_filter
        lang = language or lang_filter
        results = []
        for v in self._voices:
            if prov and prov.lower() != "all" and v.provider != prov.lower():
                continue
            if lang and lang.lower() != "all" and not v.language.lower().startswith(lang.lower()):
                continue
            if available_only and not v.is_available:
                continue
            results.append(v)
        return results

    def find_voice(self, voice_id: str) -> Optional[VoiceInfo]:
        for v in self._voices:
            if v.id == voice_id:
                return v
        return None

    def normalize_text(self, text: str, provider: str = "piper", language: str = "vi") -> str:
        return normalize_text_for_tts(text, provider=provider, language=language)

    def synthesize(
        self,
        text: str,
        output_path: str,
        voice_id: str,
        speed: float = 1.0,
        pitch: int = 0,
        output_format: str = "wav",
        piper_options: Optional[dict] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> dict:
        voice = self.find_voice(voice_id)
        if not voice:
            raise ValueError(f"Không tìm thấy giọng đọc có ID: {voice_id}")

        if not voice.is_available:
            raise RuntimeError(f"Giọng đọc '{voice.name}' chưa có file mô hình tại '{voice.provider_voice}'.")

        # Format output path
        out_p = Path(output_path)
        fmt = (output_format or out_p.suffix.lstrip(".") or "wav").lower()
        final_path = str(out_p.with_suffix(f".{fmt}"))

        res_path = synthesize_text_to_audio(
            text=text,
            output_path=final_path,
            provider=voice.provider,
            provider_voice=voice.provider_voice,
            speed=speed,
            pitch=pitch,
            language=voice.language,
            piper_options=piper_options,
            on_progress=on_progress,
        )

        duration_sec = 0.0
        sample_rate = 22050
        try:
            if res_path.endswith(".wav"):
                with wave.open(res_path, "rb") as wf:
                    frames = wf.getnframes()
                    rate = wf.getframerate()
                    sample_rate = rate
                    duration_sec = frames / float(rate) if rate > 0 else 0.0
            else:
                duration_sec = max(1.0, len(text.split()) / 3.0)
        except Exception:
            pass

        file_size = os.path.getsize(res_path) if os.path.exists(res_path) else 0

        return {
            "file_path": res_path,
            "duration_sec": duration_sec,
            "sample_rate": sample_rate,
            "file_size_bytes": file_size,
            "voice_name": voice.name,
            "provider": voice.provider,
        }

    def synthesize_preview(
        self,
        voice_id: str,
        speed: float = 1.0,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> dict:
        voice = self.find_voice(voice_id)
        if not voice:
            raise ValueError(f"Không tìm thấy giọng đọc: {voice_id}")

        if voice.language.startswith("vi"):
            preview_text = f"Xin chào, đây là giọng đọc thử nghiệm của {voice.name}."
        else:
            preview_text = f"Hello, this is a test audio preview for {voice.name}."

        temp_out = temp_path(f"preview_{voice.id}.wav")
        return self.synthesize(
            text=preview_text,
            output_path=temp_out,
            voice_id=voice_id,
            speed=speed,
            on_progress=on_progress,
        )
