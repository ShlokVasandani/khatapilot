"""Synthesize the soundtrack for the launch video (no samples, no downloads): 120 BPM, A minor, 51.5 s.
Every sound is placed on one beat grid counted from sample 0, so the scene cuts (multiples of 0.5 s) land on beats.
    python3 music.py out.wav [duration] [cut,times,...]
"""
import sys, numpy as np, wave
SR, BPM = 44100, 120
DUR = float(sys.argv[2]) if len(sys.argv) > 2 else 51.5
CUTS = [float(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else [7, 17, 24, 32, 37.5, 45]
beat = 60 / BPM
n = int(SR * DUR); t = np.arange(n) / SR
L = np.zeros(n); R = np.zeros(n)

def put(sig, at, gain=1.0, pan=0.0):
    i = int(at * SR); j = min(n, i + len(sig))
    if i >= n: return
    s = sig[: j - i] * gain
    L[i:j] += s * (1 - max(0, pan)); R[i:j] += s * (1 + min(0, pan))

def env(m, a, r): e = np.minimum(1, np.arange(m) / (a * SR)) * np.exp(-np.arange(m) / (r * SR)); return e

def note(f, dur, kind="pluck"):
    m = int(SR * dur); x = np.arange(m) / SR
    if kind == "pad":
        s = sum(np.sin(2 * np.pi * f * (1 + d) * x + p) for d, p in [(0, 0), (.003, 1), (-.004, 2), (.0015, 3)]) / 4
        s += 0.25 * np.sin(2 * np.pi * f * 2 * x)
        return s * np.minimum(1, x / 0.6) * np.minimum(1, (dur - x) / 0.8)
    s = np.sin(2 * np.pi * f * x) + .35 * np.sin(2 * np.pi * 2 * f * x) + .12 * np.sin(2 * np.pi * 3 * f * x)
    return s * env(m, .004, .22 if kind == "pluck" else .5)

def hz(m): return 440 * 2 ** ((m - 69) / 12)
bars = [(57, [57, 60, 64]), (53, [53, 57, 60]), (48, [48, 52, 55]), (55, [55, 59, 62])]   # Am F C G, 2 bars each = 4 s
chord_len = 4 * beat * 2

# pad + sub bass, whole piece
for k in range(int(DUR / chord_len) + 1):
    root, tri = bars[k % 4]; at = k * chord_len
    for m in tri: put(note(hz(m + 12), chord_len + .8, "pad"), at, .06, pan=.3 if m % 2 else -.3)
    put(note(hz(root - 12), chord_len, "bass"), at, .20)

# kick (every beat from 0, quiet before 7 s), clap on 2 and 4 from 7 s, hats on offbeats from 7 s
def kick():
    m = int(SR * .35); x = np.arange(m) / SR; f = 45 + 90 * np.exp(-x * 28)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-x * 9)
def hat(): m = int(SR * .05); return np.random.RandomState(1).randn(m) * np.exp(-np.arange(m) / (SR * .008))
def clap(): m = int(SR * .18); return np.random.RandomState(2).randn(m) * np.exp(-np.arange(m) / (SR * .035))
K = kick(); H = hat(); C = clap()
for b in range(int(DUR / beat)):
    at = b * beat
    put(K, at, .30 if at >= 7 else .16)
    if at >= 7:
        put(H, at + beat / 2, .035, pan=.4)
        if b % 2 == 1: put(C, at, .06)

# arpeggio pluck from 7 s: 8th notes through the current chord, up an octave
for s in range(int(7 / (beat / 2)), int(DUR / (beat / 2))):
    at = s * beat / 2
    k = int(at // chord_len); tri = bars[k % 4][1]
    m = tri[(s % 4) % 3] + (24 if (s % 8) >= 4 else 12)
    put(note(hz(m), .5, "pluck"), at, .045, pan=-.35 if s % 2 else .35)

# scene-cut ticks and the final hit (45.0 s)
for cut in CUTS:
    m = int(SR * .5); x = np.arange(m) / SR
    sweep = np.random.RandomState(3).randn(m) * np.exp(-x * 7) * np.minimum(1, x / .02)
    put(sweep, cut, .05); put(np.sin(2 * np.pi * 80 * x) * np.exp(-x * 6), cut, .25)
# intro and outro fades
fade_in = np.minimum(1, t / 0.8); fade_out = np.minimum(1, (DUR - t) / 2.5)
L *= fade_in * fade_out; R *= fade_in * fade_out
peak = max(np.abs(L).max(), np.abs(R).max()); L, R = L / peak * .85, R / peak * .85
out = np.stack([L, R], 1)
with wave.open(sys.argv[1], "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes((out * 32767).astype("<i2").tobytes())
print("wrote", sys.argv[1])
