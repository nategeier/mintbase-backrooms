"""A seamless 8s fluorescent-ballast hum for the Backrooms (mono WAV, 22kHz).

Magnetic ballasts hum at twice the mains frequency (120Hz) with odd-ish
harmonics, and the tubes add a thin high whine. Every tone here fits a whole
number of cycles into the loop and the noise is generated periodically, so
the loop has no seam. WAV rather than MP3: MP3's encoder padding leaves a
gap at the loop point, and Voxels takes WAV for audio features.
"""

from __future__ import annotations

import os
import sys
import wave

import numpy as np

SR = 22050
DUR = 8.0
N = int(SR * DUR)
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "out", "assets")


def periodic_noise(n: int, lo: float, hi: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / SR)
    spec[(f < lo) | (f > hi)] = 0
    x = np.fft.irfft(spec, n)
    return x / (np.abs(x).max() + 1e-9)


def main() -> None:
    t = np.arange(N) / SR
    hum = np.zeros(N)
    for f, a in ((120, 1.0), (240, 0.55), (360, 0.32), (480, 0.16), (600, 0.1), (840, 0.05)):
        hum += a * np.sin(2 * np.pi * f * t + f * 0.01)
    # the tube's whine, faint, wobbling a little
    whine = 0.035 * np.sin(2 * np.pi * 7200 * t) * (1 + 0.3 * np.sin(2 * np.pi * 0.5 * t))
    # slow beating / swell (whole cycles in 8s: 0.25Hz and 0.625Hz)
    swell = 1 + 0.12 * np.sin(2 * np.pi * 0.25 * t) + 0.05 * np.sin(2 * np.pi * 0.625 * t + 1.3)
    air = 0.06 * periodic_noise(N, 80, 3000, 7)
    buzz = 0.04 * periodic_noise(N, 2000, 6000, 8) * (0.5 + 0.5 * np.sin(2 * np.pi * 120 * t) ** 8)
    x = (hum * swell + whine + air + buzz)
    x = x / np.abs(x).max() * 0.6
    pcm = (x * 32767).astype(np.int16)
    os.makedirs(OUT, exist_ok=True)
    wav = os.path.join(OUT, "hum.wav")
    with wave.open(wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print("hum.wav", os.path.getsize(wav), "bytes")


if __name__ == "__main__":
    sys.exit(main())
