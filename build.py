#!/usr/bin/env python3
"""
Build script for Remote Desktop app.

Creates standalone executables for macOS, Windows, and Linux.
No Python installation needed by end users.

Usage:
    python build.py              # Build for current platform
    python build.py --clean      # Clean previous builds first
    python build.py --dmg        # (macOS) Also create a DMG installer
    python build.py --clean --dmg
"""

import subprocess
import sys
import os
import platform
import shutil
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_NAME = "RemoteDesktop"
APP_DISPLAY_NAME = "Remote Desktop"
ENTRY_POINT = os.path.join(SCRIPT_DIR, "app.py")
ASSETS_DIR = os.path.join(SCRIPT_DIR, "assets")
DIST_DIR = os.path.join(SCRIPT_DIR, "dist")
BUILD_DIR = os.path.join(SCRIPT_DIR, "build")

BUNDLE_ID = "com.remotedesktop.app"
VERSION = "2.0.0"


def install_pyinstaller():
    """Install PyInstaller if not present."""
    try:
        import PyInstaller
        print(f"  PyInstaller {PyInstaller.__version__}")
    except ImportError:
        print("  Installing PyInstaller...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pyinstaller"],
            stdout=subprocess.DEVNULL
        )
        print("  PyInstaller installed")


def clean():
    """Remove previous build artifacts."""
    for folder in ["build", "dist"]:
        path = os.path.join(SCRIPT_DIR, folder)
        if os.path.exists(path):
            shutil.rmtree(path)
            print(f"  Removed {folder}/")

    spec = os.path.join(SCRIPT_DIR, f"{APP_NAME}.spec")
    if os.path.exists(spec):
        os.remove(spec)
        print(f"  Removed {APP_NAME}.spec")


def get_icon_path():
    """Get the icon path for the current platform."""
    system = platform.system()
    if system == "Darwin":
        path = os.path.join(ASSETS_DIR, "icon.icns")
    elif system == "Windows":
        path = os.path.join(ASSETS_DIR, "icon.ico")
    else:
        path = os.path.join(ASSETS_DIR, "icon.png")

    if os.path.exists(path):
        return path

    # Try generating icons if they don't exist
    gen_script = os.path.join(ASSETS_DIR, "generate_icon.py")
    if os.path.exists(gen_script):
        print("  Generating app icons...")
        subprocess.check_call(
            [sys.executable, gen_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        if os.path.exists(path):
            return path

    return None


def get_hidden_imports():
    """Get platform-specific hidden imports."""
    imports = [
        "websockets",
        "websockets.client",
        "websockets.server",
        "websockets.exceptions",
        "pygame",
        "numpy",
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
        "relay",
        "relay.server",
        "relay.host_agent",
        "relay.viewer",
        "common",
        "common.protocol",
        "common.config",
        "host",
        "host.capture",
        "host.encoder",
        "client",
        "client.decoder",
        "client.connection",
        "client.viewer",
        "tkinter",
        "json",
        "struct",
        "io",
        "pyautogui",
    ]

    system = platform.system()
    if system == "Darwin":
        imports.extend([
            "Quartz",
            "Quartz.CoreGraphics",
            "objc",
            "rubicon",
            "rubicon.objc",
        ])
    elif system == "Windows":
        imports.extend([
            "mss",
            "ctypes",
            "pywintypes",
            "win32api",
            "win32con",
        ])
    elif system == "Linux":
        imports.extend([
            "mss",
            "Xlib",
        ])

    return imports


def get_data_files():
    """Get data files to include."""
    datas = []
    sep = ";" if platform.system() == "Windows" else ":"

    for pkg in ["common", "relay", "host", "client"]:
        pkg_path = os.path.join(SCRIPT_DIR, pkg)
        if os.path.exists(pkg_path):
            datas.append(f"{pkg_path}{sep}{pkg}")

    return datas


def build_executable():
    """Build the executable with PyInstaller."""
    system = platform.system()
    print(f"\n  Platform: {system} ({platform.machine()})")

    icon_path = get_icon_path()
    if icon_path:
        print(f"  Icon: {os.path.basename(icon_path)}")

    # Build PyInstaller command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--onedir",
        "--noconfirm",
        "--clean",
    ]

    # Window mode
    if system == "Darwin":
        cmd.append("--windowed")
        cmd.extend(["--osx-bundle-identifier", BUNDLE_ID])
    elif system == "Windows":
        # Use --windowed but also keep --console so viewer subprocess works
        cmd.append("--console")
    else:
        cmd.append("--console")

    # Icon
    if icon_path:
        cmd.extend(["--icon", icon_path])

    # Hidden imports
    for imp in get_hidden_imports():
        cmd.extend(["--hidden-import", imp])

    # Data files
    for data in get_data_files():
        cmd.extend(["--add-data", data])

    cmd.append(ENTRY_POINT)

    print("  Running PyInstaller...")
    subprocess.check_call(cmd, cwd=SCRIPT_DIR, stdout=subprocess.DEVNULL)

    # Verify output
    if system == "Darwin":
        app_path = os.path.join(DIST_DIR, f"{APP_NAME}.app")
        dir_path = os.path.join(DIST_DIR, APP_NAME)
        if os.path.exists(app_path):
            size = _dir_size(app_path)
            print(f"  Output: {APP_NAME}.app ({size})")
            return app_path
        elif os.path.exists(dir_path):
            size = _dir_size(dir_path)
            print(f"  Output: {APP_NAME}/ ({size})")
            return dir_path
    elif system == "Windows":
        exe_path = os.path.join(DIST_DIR, APP_NAME, f"{APP_NAME}.exe")
        if os.path.exists(exe_path):
            dir_path = os.path.join(DIST_DIR, APP_NAME)
            size = _dir_size(dir_path)
            print(f"  Output: {APP_NAME}.exe ({size})")
            return dir_path
    else:
        bin_path = os.path.join(DIST_DIR, APP_NAME, APP_NAME)
        if os.path.exists(bin_path):
            dir_path = os.path.join(DIST_DIR, APP_NAME)
            size = _dir_size(dir_path)
            print(f"  Output: {APP_NAME} ({size})")
            return dir_path

    print("  ERROR: Build output not found!")
    return None


def create_dmg(app_path: str):
    """Create a macOS DMG installer."""
    if platform.system() != "Darwin":
        print("  DMG creation only available on macOS")
        return None

    dmg_path = os.path.join(DIST_DIR, f"{APP_NAME}-macOS.dmg")

    # Remove existing DMG
    if os.path.exists(dmg_path):
        os.remove(dmg_path)

    print("  Creating DMG installer...")

    # Create a temporary directory for DMG contents
    dmg_tmp = os.path.join(BUILD_DIR, "dmg_contents")
    if os.path.exists(dmg_tmp):
        shutil.rmtree(dmg_tmp)
    os.makedirs(dmg_tmp)

    # Copy .app bundle into DMG contents
    if app_path.endswith(".app"):
        dest = os.path.join(dmg_tmp, f"{APP_NAME}.app")
        shutil.copytree(app_path, dest)
    else:
        dest = os.path.join(dmg_tmp, APP_NAME)
        shutil.copytree(app_path, dest)

    # Create Applications symlink
    os.symlink("/Applications", os.path.join(dmg_tmp, "Applications"))

    # Use hdiutil to create DMG
    try:
        subprocess.check_call([
            "hdiutil", "create",
            "-volname", APP_DISPLAY_NAME,
            "-srcfolder", dmg_tmp,
            "-ov",
            "-format", "UDZO",
            dmg_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        size_mb = os.path.getsize(dmg_path) / (1024 * 1024)
        print(f"  DMG: {os.path.basename(dmg_path)} ({size_mb:.1f} MB)")

        # Clean up
        shutil.rmtree(dmg_tmp)
        return dmg_path

    except subprocess.CalledProcessError as e:
        print(f"  DMG creation failed: {e}")
        shutil.rmtree(dmg_tmp, ignore_errors=True)
        return None


def create_zip(build_output: str):
    """Create a zip archive of the build output."""
    system = platform.system()

    if system == "Darwin":
        zip_name = f"{APP_NAME}-macOS"
    elif system == "Windows":
        zip_name = f"{APP_NAME}-Windows"
    else:
        zip_name = f"{APP_NAME}-Linux"

    zip_path = os.path.join(DIST_DIR, zip_name)

    print(f"  Creating {zip_name}.zip...")
    shutil.make_archive(zip_path, "zip", DIST_DIR, os.path.basename(build_output))

    final_path = zip_path + ".zip"
    size_mb = os.path.getsize(final_path) / (1024 * 1024)
    print(f"  ZIP: {os.path.basename(final_path)} ({size_mb:.1f} MB)")
    return final_path


def create_tar(build_output: str):
    """Create a tar.gz archive (Linux)."""
    tar_name = f"{APP_NAME}-Linux"
    tar_path = os.path.join(DIST_DIR, tar_name)

    print(f"  Creating {tar_name}.tar.gz...")
    shutil.make_archive(tar_path, "gztar", DIST_DIR, os.path.basename(build_output))

    final_path = tar_path + ".tar.gz"
    size_mb = os.path.getsize(final_path) / (1024 * 1024)
    print(f"  TAR: {os.path.basename(final_path)} ({size_mb:.1f} MB)")
    return final_path


def _dir_size(path: str) -> str:
    """Get human-readable directory size."""
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.exists(fp):
                total += os.path.getsize(fp)

    if total > 1024 * 1024 * 1024:
        return f"{total / (1024**3):.1f} GB"
    elif total > 1024 * 1024:
        return f"{total / (1024**2):.1f} MB"
    elif total > 1024:
        return f"{total / 1024:.1f} KB"
    return f"{total} B"


def main():
    parser = argparse.ArgumentParser(description=f"Build {APP_DISPLAY_NAME}")
    parser.add_argument("--clean", action="store_true",
                        help="Clean previous builds first")
    parser.add_argument("--dmg", action="store_true",
                        help="Create macOS DMG installer")
    parser.add_argument("--zip", action="store_true",
                        help="Create zip archive of build")
    args = parser.parse_args()

    system = platform.system()

    print(f"""
+======================================+
|   {APP_DISPLAY_NAME} - Build Tool        |
+--------------------------------------+
|   Version:  {VERSION:<25}|
|   Platform: {system:<25}|
+======================================+
""")

    # Step 1: Clean
    if args.clean:
        print("[1/4] Cleaning...")
        clean()
    else:
        print("[1/4] Clean: skipped (use --clean)")

    # Step 2: Check dependencies
    print("[2/4] Checking dependencies...")
    install_pyinstaller()

    # Step 3: Build
    print("[3/4] Building executable...")
    build_output = build_executable()
    if not build_output:
        print("\nBuild FAILED!")
        sys.exit(1)

    # Step 4: Package
    print("[4/4] Packaging...")
    artifacts = [build_output]

    if system == "Darwin" and args.dmg:
        dmg = create_dmg(build_output)
        if dmg:
            artifacts.append(dmg)

    if args.zip:
        zip_file = create_zip(build_output)
        artifacts.append(zip_file)

    if system == "Linux" and not args.zip:
        tar_file = create_tar(build_output)
        artifacts.append(tar_file)

    # Summary
    print(f"""
+======================================+
|   Build Complete!                    |
+======================================+

  Artifacts:""")
    for a in artifacts:
        print(f"    > {os.path.relpath(a, SCRIPT_DIR)}")

    print(f"""
  Users just double-click to run.
  No Python or terminal needed!
""")


if __name__ == "__main__":
    main()
