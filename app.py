#!/usr/bin/env python3
"""
Remote Desktop — Unified App (AnyDesk-style)

Professional dark-themed GUI with:
  - Your address code display
  - Remote address input to view others
  - Control permission dialog
  - Animated status indicators
"""

import tkinter as tk
from tkinter import messagebox
import asyncio
import threading
import subprocess
import sys
import os
import logging
import argparse

RELAY_URL = "ws://13.204.132.109:8765"

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, BASE_DIR)

from relay.host_agent import RelayHostAgent, RelayHostConfig

logger = logging.getLogger(__name__)

# ── Color Palette ──
BG_DARK = "#0d1117"
BG_CARD = "#161b22"
BG_INPUT = "#0d1117"
ACCENT = "#238636"
ACCENT_HOVER = "#2ea043"
ACCENT_BLUE = "#1f6feb"
ACCENT_RED = "#da3633"
ACCENT_ORANGE = "#d29922"
TEXT_PRIMARY = "#f0f6fc"
TEXT_SECONDARY = "#8b949e"
TEXT_DIM = "#484f58"
BORDER = "#30363d"
CODE_GREEN = "#3fb950"


class RemoteDesktopApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Remote Desktop")
        self.root.geometry("520x680")
        self.root.resizable(False, False)
        self.root.configure(bg=BG_DARK)

        try:
            self.root.iconname("Remote Desktop")
        except Exception:
            pass

        # State
        self.session_code = tk.StringVar(value="------")
        self.remote_code = tk.StringVar()
        self.status_text = tk.StringVar(value="Connecting to relay...")
        self.viewer_status = tk.StringVar(value="No viewer connected")
        self.control_status = tk.StringVar(value="Control: View Only")

        self.host_agent = None
        self.host_thread = None
        self.host_loop = None

        # Animation state
        self._pulse_state = 0
        self._dot_colors = [CODE_GREEN, "#2ea043", "#238636", "#1a7f37"]

        self._build_ui()
        self._start_animations()
        self._start_host()

    def _build_ui(self):
        # ── Header ──
        header = tk.Frame(self.root, bg=BG_DARK)
        header.pack(fill="x", padx=30, pady=(25, 0))

        tk.Label(
            header, text="Remote Desktop",
            font=("SF Pro Display", 28, "bold"),
            fg=TEXT_PRIMARY, bg=BG_DARK
        ).pack(side="left")

        # Version badge
        badge = tk.Label(
            header, text="v2.0",
            font=("SF Mono", 9), fg=TEXT_SECONDARY,
            bg="#1c2128", padx=8, pady=2
        )
        badge.pack(side="right", pady=(8, 0))

        tk.Label(
            self.root, text="Secure screen sharing across any network",
            font=("SF Pro Display", 11), fg=TEXT_SECONDARY, bg=BG_DARK
        ).pack(anchor="w", padx=30, pady=(2, 20))

        # ── Your Address Card ──
        card1 = self._create_card(self.root)

        # Card header with icon
        hdr1 = tk.Frame(card1, bg=BG_CARD)
        hdr1.pack(fill="x")

        self.status_indicator = tk.Label(
            hdr1, text=">>", font=("SF Mono", 10),
            fg=ACCENT_ORANGE, bg=BG_CARD
        )
        self.status_indicator.pack(side="left")

        tk.Label(
            hdr1, text="YOUR ADDRESS",
            font=("SF Pro Display", 10, "bold"),
            fg=TEXT_SECONDARY, bg=BG_CARD
        ).pack(side="left", padx=(6, 0))

        # Code display
        code_frame = tk.Frame(card1, bg="#0d1117", highlightbackground=BORDER,
                             highlightthickness=1)
        code_frame.pack(fill="x", pady=(12, 8))

        self.code_label = tk.Label(
            code_frame, textvariable=self.session_code,
            font=("SF Mono", 42, "bold"),
            fg=CODE_GREEN, bg="#0d1117", pady=12
        )
        self.code_label.pack()

        # Info + copy button row
        info_row = tk.Frame(card1, bg=BG_CARD)
        info_row.pack(fill="x")

        tk.Label(
            info_row, text="Share this code with the viewer",
            font=("SF Pro Display", 10), fg=TEXT_DIM, bg=BG_CARD
        ).pack(side="left")

        self.copy_btn = tk.Button(
            info_row, text="Copy",
            font=("SF Mono", 9, "bold"),
            bg="#21262d", fg=TEXT_PRIMARY,
            activebackground="#30363d", activeforeground=TEXT_PRIMARY,
            relief="flat", padx=12, pady=2, bd=0,
            cursor="hand2",
            command=self._copy_code
        )
        self.copy_btn.pack(side="right")

        # Viewer status
        self.viewer_label = tk.Label(
            card1, textvariable=self.viewer_status,
            font=("SF Pro Display", 10), fg=TEXT_DIM, bg=BG_CARD
        )
        self.viewer_label.pack(anchor="w", pady=(8, 0))

        # ── Control Section ──
        self.control_frame = self._create_card(self.root)

        ctrl_hdr = tk.Frame(self.control_frame, bg=BG_CARD)
        ctrl_hdr.pack(fill="x")

        tk.Label(
            ctrl_hdr, text="REMOTE CONTROL",
            font=("SF Pro Display", 10, "bold"),
            fg=TEXT_SECONDARY, bg=BG_CARD
        ).pack(side="left")

        self.control_label = tk.Label(
            ctrl_hdr, textvariable=self.control_status,
            font=("SF Mono", 9), fg=ACCENT_BLUE, bg=BG_CARD
        )
        self.control_label.pack(side="right")

        ctrl_btns = tk.Frame(self.control_frame, bg=BG_CARD)
        ctrl_btns.pack(fill="x", pady=(10, 0))

        self.grant_btn = tk.Button(
            ctrl_btns, text="Grant Access",
            font=("SF Pro Display", 11, "bold"),
            bg=ACCENT, fg="white",
            activebackground=ACCENT_HOVER, activeforeground="white",
            relief="flat", padx=20, pady=6, bd=0,
            cursor="hand2",
            command=self._grant_control,
            state="disabled"
        )
        self.grant_btn.pack(side="left", expand=True, fill="x", padx=(0, 5))

        self.revoke_btn = tk.Button(
            ctrl_btns, text="Revoke Access",
            font=("SF Pro Display", 11, "bold"),
            bg=ACCENT_RED, fg="white",
            activebackground="#b62324", activeforeground="white",
            relief="flat", padx=20, pady=6, bd=0,
            cursor="hand2",
            command=self._revoke_control,
            state="disabled"
        )
        self.revoke_btn.pack(side="right", expand=True, fill="x", padx=(5, 0))

        # ── Remote Address Card ──
        card2 = self._create_card(self.root)

        hdr2 = tk.Frame(card2, bg=BG_CARD)
        hdr2.pack(fill="x")

        tk.Label(
            hdr2, text="<<",
            font=("SF Mono", 10), fg=ACCENT_BLUE, bg=BG_CARD
        ).pack(side="left")

        tk.Label(
            hdr2, text="CONNECT TO REMOTE",
            font=("SF Pro Display", 10, "bold"),
            fg=TEXT_SECONDARY, bg=BG_CARD
        ).pack(side="left", padx=(6, 0))

        # Code input
        self.code_entry = tk.Entry(
            card2, textvariable=self.remote_code,
            font=("SF Mono", 24, "bold"),
            justify="center",
            bg=BG_INPUT, fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY,
            highlightbackground=BORDER,
            highlightthickness=1,
            highlightcolor=ACCENT_BLUE,
            relief="flat", bd=8
        )
        self.code_entry.pack(fill="x", pady=(12, 10))

        self.remote_code.trace_add("write", self._on_code_input)

        # Connect button
        self.connect_btn = tk.Button(
            card2, text="Connect",
            font=("SF Pro Display", 13, "bold"),
            bg=ACCENT_BLUE, fg="white",
            activebackground="#388bfd", activeforeground="white",
            relief="flat", pady=10, bd=0,
            cursor="hand2",
            command=self._connect_remote
        )
        self.connect_btn.pack(fill="x", pady=(2, 4))

        tk.Label(
            card2, text="Enter the 6-character address to view their screen",
            font=("SF Pro Display", 9), fg=TEXT_DIM, bg=BG_CARD
        ).pack()

        self.code_entry.bind("<Return>", lambda e: self._connect_remote())

        # ── Status Bar ──
        status_bar = tk.Frame(self.root, bg="#010409")
        status_bar.pack(side="bottom", fill="x")

        status_inner = tk.Frame(status_bar, bg="#010409")
        status_inner.pack(fill="x", padx=20, pady=8)

        self.status_dot = tk.Label(
            status_inner, text="*",
            font=("SF Mono", 12), fg=ACCENT_ORANGE, bg="#010409"
        )
        self.status_dot.pack(side="left")

        tk.Label(
            status_inner, textvariable=self.status_text,
            font=("SF Mono", 10), fg=TEXT_SECONDARY, bg="#010409"
        ).pack(side="left", padx=(6, 0))

        # Keyboard shortcut hint
        tk.Label(
            status_inner, text="F8: Request Control",
            font=("SF Mono", 9), fg=TEXT_DIM, bg="#010409"
        ).pack(side="right")

    def _create_card(self, parent):
        """Create a styled card frame."""
        outer = tk.Frame(parent, bg=BORDER)
        outer.pack(fill="x", padx=28, pady=(0, 12))
        inner = tk.Frame(outer, bg=BG_CARD, padx=18, pady=14)
        inner.pack(fill="x", padx=1, pady=1)
        return inner

    # ── Animations ──

    def _start_animations(self):
        """Start pulsing status indicator."""
        self._animate_pulse()

    def _animate_pulse(self):
        """Animate the status dot with a pulse effect."""
        if not self.root.winfo_exists():
            return

        self._pulse_state = (self._pulse_state + 1) % 4
        color = self._dot_colors[self._pulse_state]

        # Only pulse if connected
        code = self.session_code.get()
        if code not in ("------", "OFFLINE", "ERROR"):
            self.status_dot.configure(fg=color)

        self.root.after(500, self._animate_pulse)

    # ── Input handling ──

    def _on_code_input(self, *args):
        val = self.remote_code.get().upper().replace(" ", "")
        if len(val) > 6:
            val = val[:6]
        if val != self.remote_code.get():
            self.remote_code.set(val)

    def _copy_code(self):
        code = self.session_code.get()
        if code and code not in ("------", "OFFLINE", "ERROR"):
            self.root.clipboard_clear()
            self.root.clipboard_append(code)
            old = self.copy_btn.cget("text")
            self.copy_btn.configure(text="Copied!", bg=ACCENT)
            self.root.after(1500, lambda: self.copy_btn.configure(text=old, bg="#21262d"))

    # ── Host (share your screen) ──

    def _start_host(self):
        def run_host():
            self.host_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.host_loop)

            config = RelayHostConfig(
                relay_url=RELAY_URL,
                capture_fps=30,
                jpeg_quality=70
            )
            self.host_agent = RelayHostAgent(config)

            # Set control request callback
            self.host_agent.set_control_callback(
                lambda: self.root.after(0, self._on_control_requested)
            )

            try:
                connected = self.host_loop.run_until_complete(
                    self.host_agent.connect_to_relay()
                )

                if connected:
                    code = self.host_agent.session_code
                    self.root.after(0, lambda: self._on_host_connected(code))
                    self.host_loop.run_until_complete(self.host_agent.start())
                else:
                    self.root.after(0, self._on_host_failed)
            except Exception as e:
                logger.error(f"Host error: {e}")
                self.root.after(0, lambda: self._on_host_error(str(e)))

        self.host_thread = threading.Thread(target=run_host, daemon=True)
        self.host_thread.start()

    def _on_host_connected(self, code):
        self.session_code.set(code)
        self.status_text.set("Ready -- screen sharing active")
        self.status_dot.configure(fg=CODE_GREEN)
        self.status_indicator.configure(fg=CODE_GREEN)
        self._dot_colors = [CODE_GREEN, "#2ea043", "#238636", "#1a7f37"]

    def _on_host_failed(self):
        self.session_code.set("OFFLINE")
        self.status_text.set("Cannot reach relay server")
        self.status_dot.configure(fg=ACCENT_RED)
        self.status_indicator.configure(fg=ACCENT_RED)

    def _on_host_error(self, error):
        self.session_code.set("ERROR")
        self.status_text.set(f"Error: {error[:40]}")
        self.status_dot.configure(fg=ACCENT_RED)
        self.status_indicator.configure(fg=ACCENT_RED)

    # ── Remote Control ──

    def _on_control_requested(self):
        """Show dialog when viewer requests control."""
        self.control_status.set("Control: REQUESTED")
        self.control_label.configure(fg=ACCENT_ORANGE)
        self.grant_btn.configure(state="normal")

        # Flash the window
        self.root.bell()
        self.root.attributes('-topmost', True)
        self.root.after(100, lambda: self.root.attributes('-topmost', False))

    def _grant_control(self):
        """Grant remote control to viewer."""
        if self.host_agent and self.host_loop:
            asyncio.run_coroutine_threadsafe(
                self.host_agent.grant_control(), self.host_loop
            )
            self.control_status.set("Control: FULL ACCESS")
            self.control_label.configure(fg=ACCENT_RED)
            self.grant_btn.configure(state="disabled")
            self.revoke_btn.configure(state="normal")
            self.viewer_status.set("Viewer has full control")
            self.viewer_label.configure(fg=ACCENT_RED)

    def _revoke_control(self):
        """Revoke remote control from viewer."""
        if self.host_agent and self.host_loop:
            asyncio.run_coroutine_threadsafe(
                self.host_agent.revoke_control(), self.host_loop
            )
            self.control_status.set("Control: View Only")
            self.control_label.configure(fg=ACCENT_BLUE)
            self.grant_btn.configure(state="disabled")
            self.revoke_btn.configure(state="disabled")
            self.viewer_status.set("Viewer connected (view only)")
            self.viewer_label.configure(fg=TEXT_DIM)

    # ── Viewer (connect to remote) ──

    def _connect_remote(self):
        code = self.remote_code.get().strip().upper()

        if len(code) != 6:
            messagebox.showwarning(
                "Invalid Code",
                "Please enter a 6-character address code."
            )
            return

        if getattr(sys, 'frozen', False):
            subprocess.Popen([
                sys.executable,
                "--viewer", "--code", code
            ])
        else:
            subprocess.Popen([
                sys.executable,
                os.path.join(BASE_DIR, "app.py"),
                "--viewer", "--code", code
            ])

        self.status_text.set(f"Connecting to {code}...")

    # ── Main loop ──

    def run(self):
        try:
            self.root.mainloop()
        finally:
            if self.host_agent and self.host_loop:
                try:
                    asyncio.run_coroutine_threadsafe(
                        self.host_agent.stop(), self.host_loop
                    )
                except Exception:
                    pass


def run_viewer(code: str, scale: float = 1.0):
    """Run the viewer in a separate process."""
    from relay.viewer import RelayViewer

    print(f"Connecting to {code}...")

    async def start():
        viewer = RelayViewer(RELAY_URL, code, scale)
        await viewer.run()

    try:
        asyncio.run(start())
    except KeyboardInterrupt:
        print("Disconnected.")


def main():
    parser = argparse.ArgumentParser(
        description="Remote Desktop -- Share & View Screens",
        add_help=True
    )
    parser.add_argument("--viewer", action="store_true",
                       help="Launch in viewer mode")
    parser.add_argument("--code", type=str, default="",
                       help="Session code to connect to (viewer mode)")
    parser.add_argument("--scale", type=float, default=1.0,
                       help="Display scale for viewer (default: 1.0)")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug logging")

    args = parser.parse_args()

    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    if args.viewer:
        code = args.code.upper().strip()
        if len(code) != 6:
            print("Error: Please provide a valid 6-character session code.")
            print("Usage: app.py --viewer --code XXXXXX")
            sys.exit(1)
        run_viewer(code, args.scale)
    else:
        app = RemoteDesktopApp()
        app.run()


if __name__ == "__main__":
    main()
