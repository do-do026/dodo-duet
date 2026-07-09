import sys, json
import numpy as np
import essentia.standard as es

def analyze(path):
    sr = 44100
    audio = es.MonoLoader(filename=path, sampleRate=sr)()
    result = {}

    bpm, beats, conf, _, _ = es.RhythmExtractor2013(method="multifeature")(audio)
    key, scale, strength = es.KeyExtractor()(audio)
    result["bpm"] = round(float(bpm), 1)
    result["key"] = f"{key} {scale}"
    result["key_strength"] = round(float(strength), 3)

    frameSize, hopSize = 4096, 2048
    w = es.Windowing(type='blackmanharris62')
    spectrum = es.Spectrum()
    specpeaks = es.SpectralPeaks(orderBy='magnitude', magnitudeThreshold=0.00001,
                                  minFrequency=40, maxFrequency=5000, maxPeaks=60)
    hpcp_algo = es.HPCP(size=36)
    centroid = es.Centroid(range=sr/2)
    energy_algo = es.Energy()
    flux = es.Flux()

    hpcps, centroids, energies, fluxes = [], [], [], []
    for frame in es.FrameGenerator(audio, frameSize=frameSize, hopSize=hopSize):
        spec = spectrum(w(frame))
        freqs, mags = specpeaks(spec)
        hpcps.append(hpcp_algo(freqs, mags))
        centroids.append(centroid(spec))
        energies.append(energy_algo(frame))
        fluxes.append(flux(spec))
    hpcps = np.array(hpcps)
    centroids = np.array(centroids)
    energies = np.array(energies)
    fluxes = np.array(fluxes)
    frame_dur = hopSize / sr
    n = len(energies)

    chords, chord_strengths = es.ChordsDetection(hopSize=hopSize)(hpcps.astype(np.float32))
    chord_timeline = []
    prev = None
    for i, c in enumerate(chords):
        if c != prev:
            chord_timeline.append({"t": round(i*frame_dur, 1), "chord": c})
            prev = c
    cleaned = []
    for j, seg in enumerate(chord_timeline):
        end = chord_timeline[j+1]["t"] if j+1 < len(chord_timeline) else n*frame_dur
        if end - seg["t"] >= 1.0:
            cleaned.append(seg)
    result["chords"] = cleaned

    win = int(30 / frame_dur); step = int(10 / frame_dur)
    key_curve = []
    key_algo = es.Key()
    for start in range(0, max(1, len(hpcps)-win), step):
        seg_hpcp = np.mean(hpcps[start:start+win], axis=0)
        k, s, kstr, _ = key_algo(seg_hpcp.astype(np.float32))
        key_curve.append({"t": round(start*frame_dur, 0), "key": f"{k} {s}", "str": round(float(kstr),2)})
    result["key_curve"] = key_curve

    feat = np.stack([energies/(energies.max()+1e-9), centroids/(centroids.max()+1e-9)], axis=1)
    sec = int(1/frame_dur)
    secs = min(len(feat)//sec, 600)
    agg = np.array([feat[i*sec:(i+1)*sec].mean(axis=0) for i in range(secs)])
    novelty = np.zeros(secs)
    k = 8
    for i in range(k, secs-k):
        novelty[i] = np.linalg.norm(agg[i:i+k].mean(axis=0) - agg[i-k:i].mean(axis=0))
    bounds = [0]
    thr = novelty.mean() + novelty.std()
    i = k
    while i < secs-k:
        if novelty[i] > thr and novelty[i] == novelty[max(0,i-5):i+5].max():
            if i - bounds[-1] >= 10:
                bounds.append(i)
            i += 10
        else:
            i += 1
    bounds.append(secs)
    segments = []
    e_sec = np.array([energies[j*sec:(j+1)*sec].mean() for j in range(secs)])
    e_max = e_sec.max()+1e-9
    for j in range(len(bounds)-1):
        a, b = bounds[j], bounds[j+1]
        lvl = e_sec[a:b].mean()/e_max
        label = "high" if lvl > 0.55 else ("mid" if lvl > 0.25 else "low")
        segments.append({"start": int(a), "end": int(b), "energy_level": round(float(lvl),2), "intensity": label})
    result["segments"] = segments

    bri_curve = []
    step5 = int(5/frame_dur)
    for i in range(0, n, step5):
        bri_curve.append({"t": round(i*frame_dur,0), "brightness": round(float(centroids[i:i+step5].mean()),0)})
    result["brightness_curve"] = bri_curve

    scale_v = 0.65 if scale == "major" else 0.35
    bpm_norm = min(float(bpm)/160, 1.0)

    e_norm = float(np.percentile(energies, 75) / (np.percentile(energies, 99)+1e-9))
    f_norm = float(fluxes.mean() / (fluxes.max()+1e-9))
    arousal = round(0.4*e_norm + 0.3*bpm_norm + 0.3*f_norm, 2)
    bri_norm = min(float(centroids.mean())/3000, 1.0)
    valence = round(0.55*scale_v + 0.45*bri_norm, 2)
    quad = ("激昂/欢快" if valence>=0.5 else "紧张/愤怒") if arousal>=0.5 else ("平静/温柔" if valence>=0.5 else "忧郁/悲伤")
    result["emotion_overall"] = {"arousal": arousal, "valence": valence, "quadrant": quad}

    emo_traj = []
    for seg in segments:
        a = int(seg["start"]/frame_dur); b = min(int(seg["end"]/frame_dur), n)
        if b <= a: continue
        se = energies[a:b]; sf = fluxes[a:b]; sc = centroids[a:b]
        e_n = float(np.percentile(se,75)/(np.percentile(energies,99)+1e-9))
        f_n = float(sf.mean()/(fluxes.max()+1e-9))
        s_ar = round(min(0.45*e_n + 0.25*bpm_norm + 0.3*f_n, 1.0), 2)
        b_n = min(float(sc.mean())/3000, 1.0)
        s_va = round(0.55*scale_v + 0.45*b_n, 2)
        q = ("激昂/欢快" if s_va>=0.5 else "紧张/愤怒") if s_ar>=0.5 else ("平静/温柔" if s_va>=0.5 else "忧郁/悲伤")
        emo_traj.append({"start": seg["start"], "end": seg["end"],
                         "arousal": s_ar, "valence": s_va, "quadrant": q})
    result["emotion_trajectory"] = emo_traj

    step2 = int(2/frame_dur)
    result["energy"] = [{"t": round(i*frame_dur,0), "e": round(float(energies[i:i+step2].mean()),1)} for i in range(0, n, step2)]

    print(json.dumps(result, ensure_ascii=False))

analyze(sys.argv[1])
