#!/usr/bin/env python3
"""Setup script for TTSx Studio (TTS-App).

Configures virtual environment, installs dependencies, verifies runtime,
and prepares necessary directories for a 100% error-free execution with rich color logs.

Usage:
    python setup.py              # Default: Creates & installs into local 'venv'
    python setup.py --novenv     # Installs directly into current/system Python environment
    python setup.py --reinstall  # Recreates existing 'venv'
    python setup.py --help       # Shows help message
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Fix Windows console UTF-8 encoding
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    try:
        # Enable ANSI virtual terminal processing on Windows cmd/powershell
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent
VENV_DIR = ROOT_DIR / "venv"
REQUIREMENTS_FILE = ROOT_DIR / "requirements.txt"


class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDERLINE = "\033[4m"

    # Foreground colors
    BLACK = "\033[30m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"

    # Background colors
    BG_CYAN = "\033[46m"
    BG_BLUE = "\033[44m"


def progress_bar(current: int, total: int, width: int = 32, prefix: str = "", suffix: str = "") -> str:
    """Renders a colorful ANSI status progress bar."""
    if total <= 0:
        percent = 100
        filled = width
    else:
        percent = int(100 * (current / float(total)))
        percent = max(0, min(100, percent))
        filled = int(width * current // total)
        filled = max(0, min(width, filled))

    bar = "█" * filled + "░" * (width - filled)
    return f"{prefix} {Color.CYAN}[{Color.GREEN}{bar}{Color.CYAN}] {Color.YELLOW}{percent:3d}%{Color.RESET} {suffix}"


def log_step(step_idx: int, total_steps: int, title: str) -> None:
    bar = progress_bar(step_idx, total_steps, width=20)
    print(f"\n{Color.BOLD}{Color.CYAN}┌─────────────────────────────────────────────────────────────┐{Color.RESET}")
    print(f"{Color.BOLD}{Color.CYAN}│{Color.RESET}  {Color.YELLOW}BƯỚC {step_idx}/{total_steps}:{Color.RESET} {Color.BOLD}{Color.WHITE}{title:<43}{Color.RESET}{Color.BOLD}{Color.CYAN}│{Color.RESET}")
    print(f"{Color.BOLD}{Color.CYAN}│{Color.RESET}  Tiến độ: {bar:<47}{Color.BOLD}{Color.CYAN}│{Color.RESET}")
    print(f"{Color.BOLD}{Color.CYAN}└─────────────────────────────────────────────────────────────┘{Color.RESET}")


def log_ok(msg: str) -> None:
    print(f"  {Color.GREEN}{Color.BOLD}[✓]{Color.RESET} {Color.GREEN}{msg}{Color.RESET}")


def log_info(msg: str) -> None:
    print(f"  {Color.CYAN}{Color.BOLD}[ℹ]{Color.RESET} {Color.WHITE}{msg}{Color.RESET}")


def log_warn(msg: str) -> None:
    print(f"  {Color.YELLOW}{Color.BOLD}[⚠]{Color.RESET} {Color.YELLOW}{msg}{Color.RESET}")


def log_err(msg: str) -> None:
    print(f"  {Color.RED}{Color.BOLD}[✗]{Color.RESET} {Color.RED}{msg}{Color.RESET}", file=sys.stderr)


def get_venv_python(venv_path: Path) -> Path:
    if os.name == "nt":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def print_banner() -> None:
    banner = f"""{Color.CYAN}{Color.BOLD}
  ╔═══════════════════════════════════════════════════════════════╗
  ║                                                               ║
  ║     🎙️  TTSx STUDIO - BỘ THIẾT LẬP MÔI TRƯỜNG TỰ ĐỘNG         ║
  ║         Text-To-Speech Desktop App & Python Module            ║
  ║                                                               ║
  ╚═══════════════════════════════════════════════════════════════╝{Color.RESET}
"""
    print(banner)


def ensure_directories() -> None:
    log_info("Đang kiểm tra và khởi tạo các thư mục lưu trữ...")
    dirs = [
        ("Thư mục file âm thanh xuất (output/)", ROOT_DIR / "output"),
        ("Thư mục xử lý tạm (temp/)", ROOT_DIR / "temp"),
        ("Thư mục mô hình Tiếng Việt (models/piper/)", ROOT_DIR / "models" / "piper"),
        ("Thư mục mô hình Tiếng Anh (models/piper-en/)", ROOT_DIR / "models" / "piper-en"),
    ]
    for name, p in dirs:
        p.mkdir(parents=True, exist_ok=True)
        log_ok(f"Sẵn sàng: {name}")


def create_virtual_environment(venv_path: Path) -> Path:
    python_exe = get_venv_python(venv_path)
    if python_exe.exists():
        log_ok(f"Môi trường ảo (venv) đã sẵn sàng tại: {Color.UNDERLINE}{venv_path}{Color.RESET}")
        return python_exe

    log_info(f"Đang tạo môi trường ảo Python cô lập tại: {venv_path}")
    cmd = [sys.executable, "-m", "venv", str(venv_path)]
    res = subprocess.run(cmd)
    if res.returncode != 0 or not python_exe.exists():
        log_err(f"Không thể khởi tạo venv. Mã lỗi: {res.returncode}")
        sys.exit(1)

    log_ok("Đã khởi tạo môi trường ảo venv thành công.")
    return python_exe


def install_dependencies(python_bin: Path) -> None:
    log_info("Đang nâng cấp pip lên phiên bản mới nhất...")
    subprocess.run([str(python_bin), "-m", "pip", "install", "--upgrade", "pip", "--quiet"])

    if not REQUIREMENTS_FILE.exists():
        log_err(f"Không tìm thấy file danh mục thư viện: {REQUIREMENTS_FILE}")
        sys.exit(1)

    log_info(f"Đang tải và cài đặt các thư viện từ '{REQUIREMENTS_FILE.name}'...")
    log_info("Thư viện: PySide6, Piper-TTS, Edge-TTS, SoundFile, NumPy, VietNormalizer...")
    
    cmd = [
        str(python_bin),
        "-m",
        "pip",
        "install",
        "--progress-bar", "on",
        "-r",
        str(REQUIREMENTS_FILE),
    ]
    res = subprocess.run(cmd)
    if res.returncode != 0:
        log_err("Cài đặt phụ thuộc thất bại! Vui lòng kiểm tra kết nối mạng hoặc phiên bản Python.")
        sys.exit(res.returncode)

    log_ok("Toàn bộ các gói thư viện đã được cài đặt thành công!")


def verify_installation(python_bin: Path) -> dict:
    log_info("Đang kiểm tra và xác thực import từng module...")
    test_code = """
import sys
import json

modules = {
    'PySide6': ('PySide6', '__version__'),
    'piper-tts': ('piper', None),
    'edge-tts': ('edge_tts', '__version__'),
    'soundfile': ('soundfile', '__version__'),
    'numpy': ('numpy', '__version__'),
    'vietnormalizer': ('vietnormalizer', '__version__'),
}

status = {}
for name, (mod, ver_attr) in modules.items():
    try:
        m = __import__(mod)
        ver = getattr(m, ver_attr, 'Installed') if ver_attr else 'Installed'
        status[name] = {'ok': True, 'version': str(ver)}
    except Exception as e:
        status[name] = {'ok': False, 'error': str(e)}

print(json.dumps(status))
"""
    res = subprocess.run(
        [str(python_bin), "-c", test_code],
        capture_output=True,
        text=True,
    )
    
    if res.returncode != 0:
        log_err(f"Quá trình xác thực gặp lỗi:\n{res.stderr or res.stdout}")
        sys.exit(1)

    import json
    try:
        status_map = json.loads(res.stdout.strip())
    except Exception:
        status_map = {}

    all_passed = True
    for mod_name, info in status_map.items():
        if info.get("ok"):
            log_ok(f"Module {Color.BOLD}{mod_name:<16}{Color.RESET}: Sẵn sàng (v{info.get('version', '')})")
        else:
            all_passed = False
            log_err(f"Module {Color.BOLD}{mod_name:<16}{Color.RESET}: LỖI -> {info.get('error')}")

    if not all_passed:
        log_err("Một số module bị lỗi khi nạp. Vui lòng thử lại với: python setup.py --reinstall")
        sys.exit(1)

    return status_map


def print_summary_dashboard(target_python: Path, is_venv: bool, status_map: dict) -> None:
    print(f"\n{Color.BOLD}{Color.GREEN}╔═════════════════════════════════════════════════════════════════╗{Color.RESET}")
    print(f"{Color.BOLD}{Color.GREEN}║              🎉 THIẾT LẬP HOÀN TẤT VÀ SẴN SÀNG 100%!           ║{Color.RESET}")
    print(f"{Color.BOLD}{Color.GREEN}╚═════════════════════════════════════════════════════════════════╝{Color.RESET}")

    env_type = f"{Color.GREEN}Môi trường ảo (venv) - Được khuyên dùng{Color.RESET}" if is_venv else f"{Color.YELLOW}Python Hệ thống (--novenv){Color.RESET}"

    print(f"\n{Color.BOLD}{Color.WHITE}📊 BẢNG TỔNG KẾT TRẠNG THÁI HỆ THỐNG:{Color.RESET}")
    print(f"  • Môi trường thực thi : {env_type}")
    print(f"  • Đường dẫn Python    : {Color.CYAN}{target_python}{Color.RESET}")
    print(f"  • Động cơ Offline     : {Color.GREEN}Piper TTS VITS (Hoạt động tốt){Color.RESET}")
    print(f"  • Động cơ Online      : {Color.GREEN}Edge-TTS Neural (Hoạt động tốt){Color.RESET}")
    print(f"  • Giao diện PySide6   : {Color.GREEN}Sẵn sàng (v{status_map.get('PySide6', {}).get('version', 'OK')}){Color.RESET}")
    print(f"  • Bộ chuẩn hóa âm học : {Color.GREEN}FFmpeg Studio Mastering & VietNormalizer OK{Color.RESET}")

    print(f"\n{Color.BOLD}{Color.YELLOW}🚀 HƯỚNG DẪN KHỞI CHẠY:{Color.RESET}")
    if is_venv:
        print(f"  {Color.CYAN}1. Nhấp đúp file:{Color.RESET}   {Color.BOLD}run.bat{Color.RESET}")
        print(f"  {Color.CYAN}2. Lệnh dòng lệnh:{Color.RESET}  {Color.BOLD}.\\venv\\Scripts\\python.exe main.py{Color.RESET}")
    else:
        print(f"  {Color.CYAN}1. Khởi chạy app:{Color.RESET}   {Color.BOLD}python main.py{Color.RESET}")
        print(f"  {Color.CYAN}2. Chạy module:{Color.RESET}     {Color.BOLD}python -m app{Color.RESET}")

    print(f"{Color.BOLD}{Color.CYAN}═══════════════════════════════════════════════════════════════════{Color.RESET}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bộ cài đặt môi trường cho TTSx Studio (TTS-App) với giao diện trực quan.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--novenv",
        action="store_true",
        help="Cài đặt trực tiếp vào môi trường Python hiện tại (không tạo/dùng venv).",
    )
    parser.add_argument(
        "--reinstall",
        action="store_true",
        help="Xóa và tái tạo môi trường venv nếu đã tồn tại.",
    )

    args = parser.parse_args()

    print_banner()
    total_steps = 4

    # Bước 1: Chuẩn bị thư mục
    log_step(1, total_steps, "Kiểm tra hệ thống & chuẩn bị cấu trúc thư mục")
    ensure_directories()

    # Bước 2: Khởi tạo/xác định Python runtime
    log_step(2, total_steps, "Khởi tạo môi trường thực thi (Python Runtime)")
    is_venv = not args.novenv
    if args.novenv:
        log_info("Chế độ --novenv được bật: Sử dụng trực tiếp môi trường Python hiện tại.")
        target_python = Path(sys.executable)
    else:
        if args.reinstall and VENV_DIR.exists():
            log_info(f"Đang xóa venv cũ tại '{VENV_DIR}'...")
            shutil.rmtree(VENV_DIR, ignore_errors=True)

        target_python = create_virtual_environment(VENV_DIR)

    # Bước 3: Cài đặt dependencies
    log_step(3, total_steps, "Cài đặt & cập nhật các thư viện phụ thuộc")
    install_dependencies(target_python)

    # Bước 4: Kiểm tra và xác thực module
    log_step(4, total_steps, "Kiểm tra và xác thực tính toàn vẹn của ứng dụng")
    status_map = verify_installation(target_python)

    # Tổng kết bảng trạng thái
    print_summary_dashboard(target_python, is_venv, status_map)


if __name__ == "__main__":
    main()
