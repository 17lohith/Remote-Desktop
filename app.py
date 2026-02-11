#!/usr/bin/env python3
"""
Remote Desktop — Unified App (AnyDesk-style)

One app that does both:
  - Shows YOUR address code (others use this to view your screen)
  - Enter a REMOTE address to view someone else's screen

Works across any network when relay is hosted on a public server (EC2).
"""

import tkinter as tk
from tkinter import messagebox
import asyncio
import threading
import subprocess
import sys
import os
import logging

# ---------------------------------------------------------------
# Relay server URL
#   Local testing : ws://127.0.0.1:8765
#   Production    : ws://<EC2_PUBLIC_IP>:8765
# ---------------------------------------------------------------
RELAY_URL = "ws://13.204.132.109:8765"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from relay.host_agent import RelayHostAgent, RelayHostConfig

logger = logging.getLogger(__name__)


class RemoteDesktopApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Remote Desktop")
        self.root.geometry("480x540")
        self.root.resizable(False, False)
        self.root.configure(bg="#1a1a2e")

        # Try to set window icon (skip if fails)
        try:
            self.root.iconname("Remote Desktop")
        except Exception:
            pass

        self.session_code = tk.StringVar(value="Connecting...")
        self.remote_code = tk.StringVar()
        self.status_text = tk.StringVar(value="Connecting to relay server...")

        self.host_agent = None
        self.host_thread = None
        self.host_loop = None

        self._build_ui()
        self._start_host()

    def _build_ui(self):
        bg = "#1a1a2e"
        card_bg = "#16213e"
        accent = "#0f3460"
        text_color = "#e0e0e0"
        code_color = "#00ff88"

        # ── Title ──
        title = tk.Label(
            self.root, text="Remote Desktop",
            font=("Helvetica", 24, "bold"),
            fg=text_color, bg=bg
        )
        title.pack(pady=(20, 3))

        subtitle = tk.Label(
            self.root, text="Share & View Screens Anywhere",
            font=("Helvetica", 11), fg="#888888", bg=bg
        )
        subtitle.pack(pady=(0, 20))

        # ── YOUR ADDRESS ──
        frame1 = tk.Frame(
            self.root, bg=card_bg, padx=20, pady=15,
            highlightbackground=accent, highlightthickness=1
        )
        frame1.pack(padx=30, fill="x")

        tk.Label(
            frame1, text="Your Address",
            font=("Helvetica", 12), fg="#888888", bg=card_bg
        ).pack(anchor="w")

        code_label = tk.Label(
            frame1, textvariable=self.session_code,
            font=("Courier", 38, "bold"),
            fg=code_color, bg=card_bg
        )
        code_label.pack(pady=(8, 4))

        tk.Label(
            frame1, text="Share this code so others can view your screen",
            font=("Helvetica", 9), fg="#666666", bg=card_bg
        ).pack()

        # Copy button
        copy_btn = tk.Button(
            frame1, text="Copy",
            font=("Helvetica", 10), bg=accent, fg="white",
            activebackground="#1a5276", activeforeground="white",
            relief="flat", padx=15, pady=2,
            command=self._copy_code
        )
        copy_btn.pack(pady=(8, 0))

        # ── Spacer ──
        tk.Frame(self.root, height=20, bg=bg).pack()

        # ── REMOTE ADDRESS ──
        frame2 = tk.Frame(
            self.root, bg=card_bg, padx=20, pady=15,
            highlightbackground=accent, highlightthickness=1
        )
        frame2.pack(padx=30, fill="x")

        tk.Label(
            frame2, text="Remote Address",
            font=("Helvetica", 12), fg="#888888", bg=card_bg
        ).pack(anchor="w")

        self.code_entry = tk.Entry(
            frame2, textvariable=self.remote_code,
            font=("Courier", 22, "bold"),
            justify="center",
            bg="#0d1b2a", fg=text_color,
            insertbackground=text_color,
            relief="flat", bd=5
        )
        self.code_entry.pack(fill="x", pady=(10, 5))

        # Auto-uppercase & limit to 6 chars
        self.remote_code.trace_add("write", self._on_code_input)

        # Connect button
        self.connect_btn = tk.Button(
            frame2, text="Connect",
            font=("Helvetica", 14, "bold"),
            bg="#0f3460", fg="white",
            activebackground="#1a5276", activeforeground="white",
            relief="flat", padx=30, pady=8,
            command=self._connect_remote
        )
        self.connect_btn.pack(pady=(10, 5))

        tk.Label(
            frame2, text="Enter the remote address to view their screen",
            font=("Helvetica", 9), fg="#666666", bg=card_bg
        ).pack()

        # Enter key triggers connect
        self.code_entry.bind("<Return>", lambda e: self._connect_remote())

        # ── Status bar ──
        status_frame = tk.Frame(self.root, bg=bg)
        status_frame.pack(side="bottom", fill="x", padx=30, pady=15)

        self.status_dot = tk.Label(
            status_frame, text="●",
            font=("Helvetica", 10), fg="yellow", bg=bg
        )
        self.status_dot.pack(side="left")

        tk.Label(
            status_frame, textvariable=self.status_text,
            font=("Helvetica", 10), fg="#888888", bg=bg
        ).pack(side="left", padx=(5, 0))

    # ── Input handling ──

    def _on_code_input(self, *args):
        """Auto-uppercase, strip spaces, limit to 6 chars."""
        val = self.remote_code.get().upper().replace(" ", "")
        if len(val) > 6:
            val = val[:6]
        # Avoid infinite trace loop
        if val != self.remote_code.get():
            self.remote_code.set(val)

    def _copy_code(self):
        """Copy session code to clipboard."""
        code = self.session_code.get()
        if code and code not in ("Connecting...", "OFFLINE", "ERROR"):
            self.root.clipboard_clear()
            self.root.clipboard_append(code)
            self.status_text.set("Code copied to clipboard!")

    # ── Host (share your screen) ──

    def _start_host(self):
        """Register with relay server in a background thread."""
        def run_host():
            self.host_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.host_loop)

            config = RelayHostConfig(
                relay_url=RELAY_URL,
                capture_fps=30,
                jpeg_quality=70
            )
            self.host_agent = RelayHostAgent(config)

            try:
                connected = self.host_loop.run_until_complete(
                    self.host_agent.connect_to_relay()
                )

                if connected:
                    code = self.host_agent.session_code
                    self.root.after(0, lambda: self._on_host_connected(code))
                    # Start streaming (blocks until stopped)
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
        self.status_text.set("Ready — sharing your screen")
        self.status_dot.configure(fg="#00ff88")

    def _on_host_failed(self):
        self.session_code.set("OFFLINE")
        self.status_text.set("Cannot reach relay server")
        self.status_dot.configure(fg="red")

    def _on_host_error(self, error):
        self.session_code.set("ERROR")
        self.status_text.set(f"Error: {error}")
        self.status_dot.configure(fg="red")

    # ── Viewer (connect to remote) ──

    def _connect_remote(self):
        """Launch viewer for the entered remote code."""
        code = self.remote_code.get().strip().upper()

        if len(code) != 6:
            messagebox.showwarning(
                "Invalid Code",
                "Please enter a 6-character address code."
            )
            return

        # Launch viewer as a separate process (avoids pygame/tkinter conflict)
        script = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "view_screen.py"
        )
        subprocess.Popen([
            sys.executable, script,
            "--relay", RELAY_URL,
            "--code", code
        ])

        self.status_text.set(f"Viewing {code}...")

    # ── Main loop ──

    def run(self):
        try:
            self.root.mainloop()
        finally:
            # Clean up host agent
            if self.host_agent and self.host_loop:
                try:
                    asyncio.run_coroutine_threadsafe(
                        self.host_agent.stop(), self.host_loop
                    )
                except Exception:
                    pass


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    app = RemoteDesktopApp()
    app.run()


if __name__ == "__main__":
    main()
