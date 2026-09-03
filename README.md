# 🎙️ TTSx Studio - Text-To-Speech Desktop App & Python Module

**TTSx Studio** là giải pháp chuyển đổi văn bản thành giọng nói (Text-To-Speech) hiệu năng cao dành cho Windows, hỗ trợ chạy song song mô hình **Offline siêu tốc (Piper TTS VITS/ONNX)** và dịch vụ **Online chất lượng cao (Edge-TTS Neural)**. 

Ứng dụng được thiết kế linh hoạt với kiến trúc kép: vừa là **ứng dụng Desktop GUI độc lập**, vừa là **thư viện/module Python tái sử dụng** cho các hệ thống khác, tích hợp sẵn bộ quản lý tải giọng Hugging Face tự động và thư viện bộ lọc xử lý âm thanh **FFmpeg Studio Mastering**.

---

## 📑 Mục lục

1. [Tính năng nổi bật](#-tính-năng-nổi-bật)
2. [Cấu trúc thư mục](#-cấu-trúc-thư-mục)
3. [Yêu cầu hệ thống & Cài đặt](#-yêu-cầu-hệ-thống--cài-đặt)
4. [Hướng dẫn sử dụng](#-hướng-dẫn-sử-dụng)
   - [Chạy ứng dụng Desktop GUI](#1-chạy-ứng-dụng-desktop-gui)
   - [Sử dụng như một Python Module](#2-sử-dụng-như-một-python-module)
5. [Thư viện Preset Xử lý Âm thanh FFmpeg (Audio Mastering Library)](#-thư-viện-preset-xử-lý-âm-thanh-ffmpeg-audio-mastering-library)
   - [Preset 1: Open Studio Natural (Mặc định)](#1-open-studio-natural-mặc-định-trong-app)
   - [Preset 2: Pure Condenser Studio](#2-pure-condenser-studio-chuẩn-micro-thu-âm-tụ-điện)
   - [Preset 3: Balanced Neutral](#3-balanced-neutral-trong-suốt--mộc-mạc)
   - [Preset 4: Podcast & Voiceover Warmth](#4-podcast--voiceover-warmth-ấm-áp--truyền-cảm)
   - [Preset 5: Radio Broadcast Presence](#5-radio-broadcast-presence-phát-thanh--bắt-tai)
   - [Preset 6: Storytelling Warm Bass](#6-storytelling-warm-bass-đọc-truyện--sâu-lắng)
   - [Preset 7: Crystal Bright Clarity](#7-crystal-bright-clarity-sách-nói--tin-tức-trong-trẻo)
   - [Preset 8: Vintage Telephone & Lo-Fi](#8-vintage-telephone--lo-fi-hiệu-ứng-đàm-thoại)
6. [Quản lý giọng đọc (Voice Catalog)](#-quản-lý-giọng-đọc-voice-catalog)

---

## ✨ Tính năng nổi bật

- **Động cơ kép Offline & Online**:
  - **Piper TTS (Offline)**: Sử dụng mô hình VITS dạng ONNX, tốc độ sinh audio thời gian thực (RTF < 0.1), hoạt động hoàn toàn không cần kết nối mạng.
  - **Edge-TTS (Online)**: Giọng đọc nơ-ron tự nhiên từ Microsoft Neural Voices với nhiều ngôn ngữ và ngữ điệu mượt mà.
- **Xử lý âm thanh Studio Mastering (FFmpeg DSP)**: Tinh chỉnh tần số bù trầm ngực, khử ồm, triệt tiêu tiếng chói kim loại và mở không gian âm học mà không làm lệch cao độ gốc (*Pitch = 0*).
- **Chuẩn hóa văn bản Tiếng Việt**: Tự động chuyển đổi số, ngày tháng, từ viết tắt và ký tự đặc biệt thông qua `vietnormalizer` kết hợp bộ quy tắc regex chuyên biệt.
- **Bộ quản lý giọng Hugging Face**: Tự động quét kho mô hình `rhasspy/piper-voices` hoặc repository tùy chọn, cho phép xem trước và tải giọng đọc một chạm.
- **Hỗ trợ Module hóa toàn diện**: Cung cấp API trực tiếp cho các backend, bot, pipeline xử lý dữ liệu hoặc ứng dụng bên ngoài.

---

## 📁 Cấu trúc thư mục

```text
TTS-App/
├── app/                        # Gói module mã nguồn chính
│   ├── __init__.py             # Public API exports & graceful fallback
│   ├── __main__.py             # Entry point cho lệnh `python -m app`
│   ├── runtime_paths.py        # Quản lý đường dẫn runtime & cấu hình root
│   ├── tts_engine.py           # Quản lý danh mục Voice & Engine điều phối
│   ├── tts_processor.py        # Bộ xử lý âm thanh, Piper VITS, Edge-TTS & FFmpeg
│   ├── ui_main_window.py       # Giao diện chính (PySide6 GUI)
│   └── ui_voice_manager.py     # Giao diện quản lý & tải giọng Hugging Face
├── assets/                     # Biểu tượng, icon và tài nguyên giao diện
├── bin/                        # Công cụ thực thi nhúng (FFmpeg portable)
├── models/                     # Thư mục chứa mô hình ONNX offline
│   ├── piper/                  # Mô hình tiếng Việt (banmai, duy, cuc, v.v.)
│   └── piper-en/               # Mô hình tiếng Anh
├── output/                     # Thư mục lưu trữ file audio xuất ra
├── main.py                     # File khởi chạy ứng dụng GUI từ thư mục gốc
├── run.bat                     # Script nhấp đúp khởi chạy trên Windows
├── setup.bat                   # Script cài đặt môi trường tự động (venv/novenv)
├── setup.py                    # Script Python quản lý môi trường & cài đặt phụ thuộc
├── requirements.txt            # Danh sách thư viện phụ thuộc
├── setting.json                # Cấu hình lưu trữ trạng thái người dùng
└── voice_catalog.json          # Metadata định nghĩa các giọng đọc
```

---

## 🔧 Yêu cầu hệ thống & Cài đặt

- **Hệ điều hành**: Windows 10/11 (64-bit).
- **Python**: Phiên bản `3.9` đến `3.12`.
- **FFmpeg**: Đã tích hợp sẵn trong thư mục `bin/ffmpeg` hoặc cấu hình qua biến môi trường `PATH`.

### Cài đặt môi trường tự động:

- **Cách 1: Khởi tạo môi trường ảo `venv` (Khuyên dùng)**
  - Nhấp đúp vào file **`setup.bat`** hoặc chạy lệnh:
    ```bash
    python setup.py
    ```
- **Cách 2: Cài trực tiếp vào Python hệ thống (`--novenv`)**
  - Chạy qua batch:
    ```bash
    setup.bat --novenv
    ```
  - Hoặc qua Python:
    ```bash
    python setup.py --novenv
    ```

---

## 🚀 Hướng dẫn sử dụng

### 1. Chạy ứng dụng Desktop GUI

Có 3 cách để khởi động giao diện đồ họa:

- **Cách 1**: Nhấp đúp vào file **`run.bat`** ở thư mục gốc.
- **Cách 2**: Chạy qua file khởi động:
  ```bash
  python main.py
  ```
- **Cách 3**: Chạy qua module package:
  ```bash
  python -m app
  ```

---

### 2. Sử dụng như một Python Module

Bạn có thể nhúng **TTSx Studio** vào bất kỳ dự án Python nào khác để tổng hợp giọng nói tự động:

#### Ví dụ 1: Sử dụng `TTSEngine` (Khuyên dùng)

```python
import os
import sys

# Thêm thư mục TTS-App vào sys.path nếu đặt ở vị trí khác
sys.path.insert(0, r"F:\Code\TTS-App")

from app import TTSEngine

# Khởi tạo engine
engine = TTSEngine()

# Lấy danh sách giọng đọc khả dụng
voices = engine.get_voices()
print(f"Số lượng giọng đọc khả dụng: {len(voices)}")

# Tổng hợp âm thanh ra file WAV
result = engine.synthesize(
    text="Xin chào, đây là âm thanh tổng hợp từ module TTSx Studio.",
    output_path="output/demo.wav",
    voice_id="ngochuyen",         # ID giọng (Piper hoặc Edge-TTS)
    speed=1.0,                    # Tốc độ (0.5 - 3.0)
    pitch=0,                      # Cao độ (-50 đến +50)
    output_format="wav",
    piper_options={
        "warm_dsp": True,          # Áp dụng bộ lọc Studio Natural DSP
    }
)

print(f"Đã tạo file thành công: {result['output_path']}")
```

#### Ví dụ 2: Tùy biến đường dẫn Root khi tích hợp hệ thống lớn

```python
from app import set_bundle_root, TTSEngine

# Thiết lập thư mục chứa models/bin tùy chỉnh
set_bundle_root("D:/CustomTTSData")

engine = TTSEngine()
```

---

## 🎛️ Thư viện Preset Xử lý Âm thanh FFmpeg (Audio Mastering Library)

Các bộ lọc dưới đây được tối ưu hóa dựa trên đối sánh phổ âm học thực tế, giúp loại bỏ các nhược điểm thường gặp của mô hình TTS VITS (tiếng nghẹt ồm, gai kim loại chói tai, thiếu độ ấm) và tạo chiều sâu không gian phòng thu.

Người dùng có thể tích chọn trực tiếp trên giao diện hoặc dán chuỗi `-af` vào mục **Custom FFmpeg**.

---

### 1. Open Studio Natural (Mặc định trong App)
> **Đặc trưng**: Bù nhẹ trầm ấm `200Hz (+2.2dB)`, khoét sạch dải ồm `420Hz (-3.8dB)`, triệt tiêu đúng 2 điểm gai kim loại `3.4kHz (-3.6dB)` và `6.2kHz (-3.5dB)`, mở trọn dải không gian `11kHz (+1.2dB)`. Âm thanh bay bổng, thoáng đãng, ấm áp tự nhiên, mở âm lượng lớn vẫn rất êm tai.

- **Chuỗi tham số FFmpeg**:
  ```text
  volume=0.92,equalizer=f=200:t=q:w=1.2:g=2.2,equalizer=f=420:t=q:w=1.6:g=-3.8,equalizer=f=3400:t=q:w=2.2:g=-3.6,equalizer=f=6200:t=q:w=2.5:g=-3.5,equalizer=f=11000:t=q:w=1.5:g=1.2
  ```
- **Lệnh FFmpeg độc lập**:
  ```bash
  ffmpeg -y -i input.wav -af "volume=0.92,equalizer=f=200:t=q:w=1.2:g=2.2,equalizer=f=420:t=q:w=1.6:g=-3.8,equalizer=f=3400:t=q:w=2.2:g=-3.6,equalizer=f=6200:t=q:w=2.5:g=-3.5,equalizer=f=11000:t=q:w=1.5:g=1.2" output.wav
  ```

---

### 2. Pure Condenser Studio (Chuẩn Micro Thu Âm Tụ Điện)
> **Đặc trưng**: Bù dải ngực `190Hz (+2.5dB)`, cắt dải đục `450Hz (-4.2dB)`, làm nổi bật khẩu hình `2.8kHz (+1.2dB)`, khoét gai gắt `3.8kHz (-3.8dB)` và `5.8kHz (-3.2dB)`, mở dải sáng `highshelf 10kHz (+1.5dB)`. Tái tạo chất âm như thu âm qua mic condenser chuyên nghiệp.

- **Chuỗi tham số FFmpeg**:
  ```text
  volume=0.92,equalizer=f=190:t=q:w=1.0:g=2.5,equalizer=f=450:t=q:w=1.8:g=-4.2,equalizer=f=2800:t=q:w=1.8:g=1.2,equalizer=f=3800:t=q:w=2.4:g=-3.8,equalizer=f=5800:t=q:w=2.5:g=-3.2,highshelf=f=10000:g=1.5
  ```
- **Lệnh FFmpeg độc lập**:
  ```bash
  ffmpeg -y -i input.wav -af "volume=0.92,equalizer=f=190:t=q:w=1.0:g=2.5,equalizer=f=450:t=q:w=1.8:g=-4.2,equalizer=f=2800:t=q:w=1.8:g=1.2,equalizer=f=3800:t=q:w=2.4:g=-3.8,equalizer=f=5800:t=q:w=2.5:g=-3.2,highshelf=f=10000:g=1.5" output.wav
  ```

---

### 3. Balanced Neutral (Trong suốt & Mộc mạc)
> **Đặc trưng**: Can thiệp tối thiểu nhằm bảo toàn tính tự nhiên gốc: bù nhẹ `210Hz (+2.0dB)`, hạ dải ồm `400Hz (-3.5dB)`, hạ nhẹ gai `3.2kHz (-3.2dB)` và `5.5kHz (-3.0dB)`.

- **Chuỗi tham số FFmpeg**:
  ```text
  volume=0.90,equalizer=f=210:t=q:w=1.0:g=2.0,equalizer=f=400:t=q:w=1.6:g=-3.5,equalizer=f=3200:t=q:w=2.0:g=-3.2,equalizer=f=5500:t=q:w=2.2:g=-3.0
  ```
- **Lệnh FFmpeg độc lập**:
  ```bash
  ffmpeg -y -i input.wav -af "volume=0.90,equalizer=f=210:t=q:w=1.0:g=2.0,equalizer=f=400:t=q:w=1.6:g=-3.5,equalizer=f=3200:t=q:w=2.0:g=-3.2,equalizer=f=5500:t=q:w=2.2:g=-3.0" output.wav
  ```

---

### 4. Podcast & Voiceover Warmth (Ấm áp & Truyền cảm)
> **Đặc trưng**: Tối ưu hóa cho các thể loại lồng tiếng, bình luận, podcast hội thoại. Tăng cường lực dải trầm ngực `160Hz (+3.0dB)`, gọt sạch dải hộp cộng hưởng `350Hz (-3.0dB)`, làm dịu dải phát âm sắc `3.2kHz (-3.0dB)` và nâng nhẹ dải thoáng `9kHz (+1.0dB)`.

- **Chuỗi tham số FFmpeg**:
  ```text
  volume=0.92,equalizer=f=160:t=q:w=1.2:g=3.0,equalizer=f=350:t=q:w=1.5:g=-3.0,equalizer=f=3200:t=q:w=2.0:g=-3.0,equalizer=f=5000:t=q:w=2.0:g=-2.5,highshelf=f=9000:g=1.0
  ```
- **Lệnh FFmpeg độc lập**:
  ```bash
  ffmpeg -y -i input.wav -af "volume=0.92,equalizer=f=160:t=q:w=1.2:g=3.0,equalizer=f=350:t=q:w=1.5:g=-3.0,equalizer=f=3200:t=q:w=2.0:g=-3.0,equalizer=f=5000:t=q:w=2.0:g=-2.5,highshelf=f=9000:g=1.0" output.wav
  ```

---

### 5. Radio Broadcast Presence (Phát thanh & Bắt tai)
> **Đặc trưng**: Dành cho đọc tin tức, video quảng cáo hoặc lồng tiếng trên nền nhạc lớn. Đẩy dải hiện diện khẩu hình `2.5kHz (+2.2dB)` và dải sáng `8kHz (+2.0dB)` kết hợp kiểm soát âm trầm `120Hz (+2.5dB)` giúp giọng đọc luôn nổi bật phía trên nhạc nền.

- **Chuỗi tham số FFmpeg**:
  ```text
  volume=0.90,equalizer=f=120:t=q:w=1.0:g=2.5,equalizer=f=500:t=q:w=1.4:g=-2.8,equalizer=f=2500:t=q:w=1.5:g=2.2,equalizer=f=4000:t=q:w=2.0:g=-2.5,highshelf=f=8000:g=2.0
  ```
- **Lệnh FFmpeg độc lập**:
  ```bash
  ffmpeg -y -i input.wav -af "volume=0.90,equalizer=f=120:t=q:w=1.0:g=2.5,equalizer=f=500:t=q:w=1.4:g=-2.8,equalizer=f=2500:t=q:w=1.5:g=2.2,equalizer=f=4000:t=q:w=2.0:g=-2.5,highshelf=f=8000:g=2.0" output.wav
  ```

---

### 6. Storytelling Warm Bass (Đọc truyện & Sâu lắng)
> **Đặc trưng**: Phù hợp cho đọc truyện đêm khuya, truyện kiếm hiệp, sách nói cảm xúc. Bù sâu dải siêu trầm `100Hz-140Hz (+3.5dB)`, triệt tiêu toàn bộ dải đục và tiếng gắt kim loại để tạo cảm giác giọng đọc dày, ấm áp và êm dịu khi nghe tai nghe trong thời gian dài.

- **Chuỗi tham số FFmpeg**:
  ```text
  volume=0.90,lowshelf=f=100:g=1.5,equalizer=f=140:t=q:w=1.0:g=3.5,equalizer=f=400:t=q:w=1.8:g=-4.0,equalizer=f=3500:t=q:w=2.2:g=-4.0,equalizer=f=6000:t=q:w=2.5:g=-3.5
  ```
- **Lệnh FFmpeg độc lập**:
  ```bash
  ffmpeg -y -i input.wav -af "volume=0.90,lowshelf=f=100:g=1.5,equalizer=f=140:t=q:w=1.0:g=3.5,equalizer=f=400:t=q:w=1.8:g=-4.0,equalizer=f=3500:t=q:w=2.2:g=-4.0,equalizer=f=6000:t=q:w=2.5:g=-3.5" output.wav
  ```

---

### 7. Crystal Bright Clarity (Sách nói & Tin tức trong trẻo)
> **Đặc trưng**: Tăng cường tối đa độ rõ ràng từng phụ âm và từ ngữ, phù hợp cho bài giảng học thuật, hướng dẫn kỹ thuật hoặc tin tức ngắn.

- **Chuỗi tham số FFmpeg**:
  ```text
  volume=0.92,equalizer=f=250:t=q:w=1.2:g=-1.5,equalizer=f=450:t=q:w=1.5:g=-3.5,equalizer=f=3000:t=q:w=1.6:g=1.8,equalizer=f=5500:t=q:w=2.2:g=-2.0,highshelf=f=10000:g=2.2
  ```
- **Lệnh FFmpeg độc lập**:
  ```bash
  ffmpeg -y -i input.wav -af "volume=0.92,equalizer=f=250:t=q:w=1.2:g=-1.5,equalizer=f=450:t=q:w=1.5:g=-3.5,equalizer=f=3000:t=q:w=1.6:g=1.8,equalizer=f=5500:t=q:w=2.2:g=-2.0,highshelf=f=10000:g=2.2" output.wav
  ```

---

### 8. Vintage Telephone & Lo-Fi (Hiệu ứng đàm thoại)
> **Đặc trưng**: Mô phỏng âm thanh điện thoại bàn cổ điển hoặc máy bộ đàm bằng cách cắt dải cao (`lowpass 3500Hz`) và dải trầm (`highpass 350Hz`), tập trung toàn bộ năng lượng vào dải trung tần `1.2kHz - 2.2kHz`.

- **Chuỗi tham số FFmpeg**:
  ```text
  volume=0.88,highpass=f=350,lowpass=f=3500,equalizer=f=1200:t=q:w=1.0:g=3.0,equalizer=f=2200:t=q:w=1.2:g=2.0
  ```
- **Lệnh FFmpeg độc lập**:
  ```bash
  ffmpeg -y -i input.wav -af "volume=0.88,highpass=f=350,lowpass=f=3500,equalizer=f=1200:t=q:w=1.0:g=3.0,equalizer=f=2200:t=q:w=1.2:g=2.0" output.wav
  ```

---

## 👥 Quản lý giọng đọc (Voice Catalog)

Hệ thống tự động nạp cấu hình giọng từ file `voice_catalog.json` và quét thư mục `models/piper/`:

- **Giọng Tiếng Việt Offline (Piper VITS)**: `banmai`, `ngochuyen`, `chieuthanh`, `cuc`, `duy`, `nam`, `vietnam`, `vbee`,...
- **Giọng Tiếng Anh Offline (Piper VITS)**: `amy`, `ryan`, `lessac`, `libritts`,...
- **Giọng Online (Edge-TTS)**: `vi-VN-HoaiMyNeural`, `vi-VN-NamMinhNeural`, `en-US-JennyNeural`, `en-US-GuyNeural`,...
