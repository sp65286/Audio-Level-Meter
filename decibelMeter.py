import tkinter as tk
import sounddevice as sd
import numpy as np
import queue

# Config
BLOCK_SIZE      = 1024
CHANNELS        = 2
UPDATE_INTERVAL = 50
DB_FLOOR        = -60     # silence floor (dBFS)
DB_CEIL         = 0       # max (0 dBFS = full volume)

# Thresholds (dBFS — negative numbers, 0 is loudest)
QUIET_MAX  = -40   # very quiet
NORMAL_MAX = -20   # normal listening
LOUD_MAX   = -10   # loud
# above -10 = very loud / clipping risk

# Colors
COLOR_BG      = "#0f0f0f"
COLOR_PANEL   = "#1a1a1a"
COLOR_TEXT    = "#e8e8e8"
COLOR_SUBTEXT = "#666666"
COLOR_GREEN   = "#4ade80"
COLOR_YELLOW  = "#facc15"
COLOR_ORANGE  = "#fb923c"
COLOR_RED     = "#f87171"

# Helpers
def rms_to_db(block: np.ndarray) -> float:
    """Convert audio block to dBFS (0 = full scale, negative = quieter)."""
    rms = np.sqrt(np.mean(block ** 2))
    if rms < 1e-10:
        return DB_FLOOR
    db = 20 * np.log10(rms)
    return max(DB_FLOOR, min(db, DB_CEIL))


def db_color(db: float) -> str:
    if db < QUIET_MAX:
        return COLOR_GREEN
    elif db < NORMAL_MAX:
        return COLOR_YELLOW
    elif db < LOUD_MAX:
        return COLOR_ORANGE
    else:
        return COLOR_RED


def db_label(db: float) -> str:
    if db < QUIET_MAX:
        return "Quiet"
    elif db < NORMAL_MAX:
        return "Normal"
    elif db < LOUD_MAX:
        return "Loud"
    else:
        return "Very Loud  ⚠"


# Audio
class AudioMonitor:
    def __init__(self, data_queue: queue.Queue):
        self.queue = data_queue
        self._stream = None

    def _find_blackhole(self):
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            if 'blackhole' in d['name'].lower() and d['max_input_channels'] > 0:
                print(f"Found BlackHole: [{i}] {d['name']} @ {d['default_samplerate']}Hz")
                return i, int(d['default_samplerate'])
        print("BlackHole not found, using default input")
        return None, 48000

    def _callback(self, indata, frames, time, status):
        db = rms_to_db(indata[:, 0])
        self.queue.put(db)

    def start(self):
        device_index, sample_rate = self._find_blackhole()
        self._stream = sd.InputStream(
            samplerate=sample_rate,
            blocksize=BLOCK_SIZE,
            channels=CHANNELS,
            device=device_index,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()


# UI
class DecibelMeterApp:
    def __init__(self, root: tk.Tk, data_queue: queue.Queue):
        self.root = root
        self.queue = data_queue
        self.peak_db = DB_FLOOR
        self.peak_timer = 0
        self.PEAK_HOLD_FRAMES = 60

        self._build_ui()

    def _build_ui(self):
        self.root.title("dB Meter")
        self.root.configure(bg=COLOR_BG)
        self.root.resizable(False, False)
        self.root.geometry("360x500")

        tk.Label(
            self.root, text="DECIBEL METER",
            bg=COLOR_BG, fg=COLOR_SUBTEXT,
            font=("Courier", 11, "bold")
        ).pack(pady=(28, 0))

        self.db_var = tk.StringVar(value="---")
        self.db_label = tk.Label(
            self.root, textvariable=self.db_var,
            bg=COLOR_BG, fg=COLOR_GREEN,
            font=("Courier", 72, "bold"),
            width=5, anchor="e"
        )
        self.db_label.pack()

        tk.Label(
            self.root, text="dBFS",
            bg=COLOR_BG, fg=COLOR_SUBTEXT,
            font=("Courier", 13)
        ).pack(pady=(0, 4))

        tk.Label(
            self.root, text="0 = max volume  •  -60 = silence",
            bg=COLOR_BG, fg=COLOR_SUBTEXT,
            font=("Courier", 9)
        ).pack(pady=(0, 6))

        self.status_var = tk.StringVar(value="Listening...")
        self.status_label = tk.Label(
            self.root, textvariable=self.status_var,
            bg=COLOR_BG, fg=COLOR_GREEN,
            font=("Courier", 14, "bold")
        )
        self.status_label.pack(pady=(0, 18))

        self.canvas = tk.Canvas(
            self.root, width=300, height=28,
            bg=COLOR_PANEL, highlightthickness=0, bd=0
        )
        self.canvas.pack(pady=(0, 6))
        self.bar = self.canvas.create_rectangle(0, 0, 0, 28, fill=COLOR_GREEN, width=0)
        self.peak_line = self.canvas.create_rectangle(0, 0, 3, 28, fill="white", width=0)

        scale_frame = tk.Frame(self.root, bg=COLOR_BG)
        scale_frame.pack()
        for val in ["-60", "-45", "-30", "-15", "0"]:
            tk.Label(
                scale_frame, text=val,
                bg=COLOR_BG, fg=COLOR_SUBTEXT,
                font=("Courier", 9)
            ).pack(side="left", padx=17)

        self.peak_var = tk.StringVar(value="Peak: ---")
        tk.Label(
            self.root, textvariable=self.peak_var,
            bg=COLOR_BG, fg=COLOR_SUBTEXT,
            font=("Courier", 11)
        ).pack(pady=(18, 0))

        tk.Button(
            self.root, text="Reset Peak",
            bg=COLOR_PANEL, fg=COLOR_TEXT,
            font=("Courier", 10), relief="flat",
            activebackground="#2a2a2a", activeforeground=COLOR_TEXT,
            cursor="hand2", padx=12, pady=5,
            command=self._reset_peak
        ).pack(pady=(10, 0))

        try:
            devices = sd.query_devices()
            device_name = next(
                (d['name'] for d in devices if 'blackhole' in d['name'].lower()),
                "BlackHole not found"
            )
        except Exception:
            device_name = "Unknown device"

        tk.Label(
            self.root, text=f"🎙  {device_name}",
            bg=COLOR_BG, fg=COLOR_SUBTEXT,
            font=("Courier", 9), wraplength=320
        ).pack(pady=(16, 0))

    def _reset_peak(self):
        self.peak_db = DB_FLOOR
        self.peak_timer = 0
        self.peak_var.set("Peak: ---")

    def _db_to_bar_x(self, db: float) -> int:
        ratio = (db - DB_FLOOR) / (DB_CEIL - DB_FLOOR)
        return int(max(0.0, min(1.0, ratio)) * 300)

    def update(self):
        db = None
        try:
            while True:
                db = self.queue.get_nowait()
        except queue.Empty:
            pass

        if db is not None:
            color = db_color(db)

            self.db_var.set(f"{db:5.1f}")
            self.db_label.configure(fg=color)
            self.status_var.set(db_label(db))
            self.status_label.configure(fg=color)

            bar_x = self._db_to_bar_x(db)
            self.canvas.coords(self.bar, 0, 0, bar_x, 28)
            self.canvas.itemconfig(self.bar, fill=color)

            if db >= self.peak_db:
                self.peak_db = db
                self.peak_timer = 0
            else:
                self.peak_timer += 1
                if self.peak_timer > self.PEAK_HOLD_FRAMES:
                    self.peak_db = db
                    self.peak_timer = 0

            peak_x = self._db_to_bar_x(self.peak_db)
            self.canvas.coords(self.peak_line, peak_x, 0, peak_x + 3, 28)
            self.peak_var.set(f"Peak: {self.peak_db:.1f} dBFS")

        self.root.after(UPDATE_INTERVAL, self.update)


# Main
def main():
    data_queue = queue.Queue()
    monitor = AudioMonitor(data_queue)
    monitor.start()

    root = tk.Tk()
    app = DecibelMeterApp(root, data_queue)
    root.after(UPDATE_INTERVAL, app.update)

    def on_close():
        monitor.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    try:
        root.mainloop()
    finally:
        monitor.stop()


if __name__ == "__main__":
    main()
