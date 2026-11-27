#!/usr/bin/env python
"""Deterministic transcript-only SAPI corpus v3 generator."""
from __future__ import annotations
import argparse, hashlib, json, math, struct, subprocess, tempfile, wave
from pathlib import Path
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt, resample_poly

SR, SAPI_SR, SEED = 16000, 22050, 5021
VOICES = ("Microsoft Zira Desktop", "Microsoft David Desktop")
SENTENCES = [
 "Bring the lantern to the north gate before dawn.", "Did you leave the cobalt key beside the harbor map?",
 "I can't tell whether Mara's coming tonight.", "Well, uh, let's try that door again.",
 "The courier said the package was already here.", "Their boat is there, but they're waiting over there.",
 "Write the right number on the white card.", "We heard the herd move past the ridge.",
 "The knight knew which route to take.", "Please send seven silver tokens to station twelve.",
 "On March the fifth, we'll meet at half past nine.", "The archive lists four hundred and sixteen names.",
 "Could you call Nessa, or should I call her?", "Rook, take the eastern path; Vela, guard the bridge.",
 "Zorin says the signal is clear, but I don't believe him.", "Captain Orla found a banana under the console.",
 "That bandana belongs to Banna, not to the band.", "The arbor stands beyond the old harbor wall.",
 "Cobol runs on the terminal; cobalt shines in the case.", "We need a harbor, not an arbor, for this boat.",
 "Banana bread again? I thought we had soup.", "Cobalt blue or navy blue—pick one quickly.",
 "Wait, wait, wait for the second bell.", "No, I mean the west door, not the wet floor.",
 "It's five past six, and the last train leaves at seven.", "I would've stayed if you'd asked me.",
 "They've packed their coats, but we haven't packed ours.", "She's sure the map's upside down.",
 "Is that your crate, or is it mine?", "You're early; we're still counting the keys.",
 "Hey! Get down!", "Run! The bridge is moving!", "Stop right there!", "Look out below!",
 "Don't touch that glowing lever.", "Keep your hands where I can see them.",
 "The quiet machine suddenly started humming.", "A blue kite drifted over the empty market.",
 "We bought two pears, too, for the twins.", "There are eight crates by the gate.",
 "The ferry leaves on June twenty-first at noon.", "At four thirty, the watch changed shifts.",
 "Nineteen lanterns lit the narrow passage.", "Mira paid thirteen credits for the compass.",
 "Vexa's notebook says, 'Turn left at the well.'", "Tell Juno that Kest is waiting outside.",
 "The name is spelled Kairn, with an a before the i.", "Say Elarin slowly: eh-lah-rin.",
 "The robot called itself NIM, then went quiet.", "Doctor Vale will arrive after the storm.",
 "A small banana rolled beneath the captain's chair.", "He peeled the banana while reading the harbor chart.",
 "The cobalt panel blinked twice, then went dark.", "They painted the harbor sign cobalt to match the buoy.",
 "A bandana covered the cracked radio speaker.", "The arbor shaded a bench near the harbor.",
 "Cobol, cobalt, and cobble sound alike when the room is loud.", "Arbor or harbor? The first has no water.",
 "I said banana, not bandana; listen again.", "Cobalt is the color, and Cobol is the code.",
 "The baker's ready, but the baker's brother isn't.", "We'll take the bear, not the bare metal frame.",
 "The cell door opened; the sailor checked his sail.", "A plain plane crossed the cloudy sky.",
 "She sent a scent sample to the center lab.", "The scene seemed peaceful until the alarm rang.",
 "I can hear you here, but I can't see you.", "The sun's low, so the son brought a lamp.",
 "Please brake before the break in the road.", "The flour flower fell into the bowl.",
 "Milo, move the red marker beside the blue one.", "Turn left at the third lamp, then stop.",
 "If the green light flashes, press the round button.", "Don't open crate nine until I return.",
 "Take one step back, then two steps forward.", "Bring three ropes, six hooks, and no ladders.",
 "Add twelve drops of water to the empty jar.", "Set the timer for forty-five seconds.",
 "We leave at eight, unless the weather turns.", "The second door is locked; the first one isn't.",
 "I thought you said the password was 'copper moon.'", "Maybe the map is wrong, or maybe we're lost.",
 "Uh, the engine—well, the engine stopped again.", "I was going to say—never mind, you heard it.",
 "It's not broken; it's just, um, thinking.", "Right, right, I know the way. Mostly.",
 "Well, that's one way to open a stubborn hatch.", "Uh-oh, somebody forgot to lower the anchor.",
 "We found the clue, but we lost the key.", "You take the stairs; I'll take the lift.",
 "The little fox ran past the fallen fence.", "A wooden wheel rolled under the wagon.",
 "Cold rain fell across the crowded station.", "The guard glanced back, then waved us through.",
 "My old radio only works near the window.", "A paper crown sat on the queen's empty chair.",
 "The drummer missed a beat, then caught the rhythm.", "Someone left warm tea beside the toolbox.",
 "The yellow marker means caution, not danger.", "A narrow tunnel leads to the hidden garden.",
 "The market opens at six every weekday.", "Our team scored two points in the final round.",
 "The parcel weighs one kilogram and three ounces.", "She borrowed twenty dollars and returned twenty-one.",
 "Meet me at seven fifteen on Friday, not Saturday.", "The year was two thousand forty-two when the beacon failed.",
 "We have a dozen minutes before the gate closes.", "The code is four, zero, eight, then four again.",
 "Is the harbor north of the lighthouse or east of it?", "Why did the little boat turn around?",
 "Who left a banana beside the emergency radio?", "Could the cobalt wire be causing that buzzing sound?",
 "Would you rather wait here or walk to the station?", "How many red flags can you see from here?",
 "That was close! The whole ceiling just shook.", "Fantastic, another locked gate and no key!",
 "Well done, Nessa; you found the hidden switch.", "I told you the old lift still worked!",
 "The crowd cheered as the lights came back on.", "A distant drumbeat echoed through the valley.",
 "Soft music played while the crew repaired the beacon.", "A slow melody looped beneath the station announcement.",
 "Click the small latch twice, then pull it gently.", "A sharp click came from inside the empty box.",
 "The wind pushed the smoke toward the eastern ridge.", "A bright flash lit the harbor for one second.",
 "The lookout shouted, 'Incoming!' and ducked behind cover.", "The blast was distant, but the windows rattled.",
 "At last, the cargo boat reached the quiet harbor.", "A ripe banana and a cobalt mug sat on the desk.",
 "The arbor gate opens with a brass key.", "Bandana, banana: say both words without rushing.",
 "Cobol is written in old manuals, not on that blue sign.", "Harbor lights blinked while the rain grew heavier.",
 "Could you repeat the last two words, please?", "I heard 'fifteen,' but did you say 'fifty'?",
 "The ship's bell rang once, twice, then three times.", "It's theirs, not ours; leave it where it was.",
 "The new route is shorter, though the old road is safer.",
 "A lantern, a compass, and a dry blanket should be enough.",
 "If Varo calls, tell him the cobalt sample arrived.",
 "When the clock strikes ten, close the outer gate.",
 "The banana crate is heavier than the bandana box.",
 "Harbor patrol found an arbor beside the old wall.",
 "Nobody knows whether Kiva or Kira sent the message.",
 "I almost had it—no, I had it, then it slipped.",
 "One more try, please; this time keep the radio close.",
 "The blue boat passed the buoy, then vanished in fog.",
 "Did they say 'their boat' or 'there, boat'?",
 "Keep the spare battery in pocket number two.",
]

PS = r"""param([string]$Text,[string]$WavPath,[string]$VoiceName,[int]$Rate,[int]$Volume)
$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.Speech
$s=New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice($VoiceName); $s.Rate=$Rate; $s.Volume=$Volume
$s.SetOutputToWaveFile($WavPath); $s.Speak($Text); $s.SetOutputToNull(); $s.Dispose()"""

def sha_bytes(b): return hashlib.sha256(b).hexdigest()
def file_sha(p): return sha_bytes(p.read_bytes())
def arr_sha(a): return sha_bytes(np.ascontiguousarray(a,dtype=np.float32).tobytes())
def write_wav(path,a):
    sf.write(str(path),np.asarray(a,dtype=np.float32),SR,subtype="FLOAT")
    b=bytearray(path.read_bytes()); i=12
    while i+8<=len(b):
        size=struct.unpack_from("<I",b,i+4)[0]
        if b[i:i+4]==b"PEAK" and size>=8: struct.pack_into("<I",b,i+12,0)
        i+=8+size+(size&1)
    path.write_bytes(b); return file_sha(path)
def norm(x):
    x=np.asarray(x,dtype=np.float32); x=x/(np.sqrt(np.mean(x.astype(np.float64)**2))+1e-12); return x
def noise(n,seed,pink=False):
    r=np.random.default_rng(seed); x=r.normal(size=n)
    if pink:
        # Deterministic low-frequency weighted spectrum, using real FFT.
        f=np.fft.rfftfreq(n); scale=1/np.sqrt(np.maximum(f,1/n)); scale[0]=0
        x=np.fft.irfft(np.fft.rfft(x)*scale,n)
    return norm(x).astype(np.float32)
def cache_speech(text,voice,rate,volume,root,cache,helper,tmp,manifest):
    key=hashlib.sha256(f"{voice}\0{rate}\0{volume}\0{text}".encode()).hexdigest()
    items=manifest["items"]
    if key not in items:
        wav=tmp/(key+".wav")
        subprocess.run(["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",str(helper),
            "-Text",text,"-WavPath",str(wav),"-VoiceName",voice,"-Rate",str(rate),"-Volume",str(volume)],
            check=True,capture_output=True,text=True)
        digest=file_sha(wav); target=cache/(digest+".wav")
        if not target.exists(): target.write_bytes(wav.read_bytes())
        items[key]={"text":text,"voice":voice,"rate":rate,"volume":volume,"wav":target.name,"sha256":digest}
        (cache/"manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    e=items[key]; p=cache/e["wav"]
    if file_sha(p)!=e["sha256"]: raise ValueError("SAPI cache hash mismatch")
    with wave.open(str(p),"rb") as w:
        ch,wid,sr=w.getnchannels(),w.getsampwidth(),w.getframerate()
        if wid!=2: raise ValueError("Expected 16-bit SAPI PCM")
        a=np.frombuffer(w.readframes(w.getnframes()),dtype="<i2").astype(np.float32)/32768
    if ch>1:a=a.reshape(-1,ch).mean(axis=1)
    return resample_poly(a.astype(np.float64),SR,sr).astype(np.float32)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--output-root",type=Path,required=True)
    ap.add_argument("--sapi-cache",type=Path,required=True)
    args=ap.parse_args(); root=args.output_root.resolve(); cache=args.sapi_cache.resolve()
    out=root/"audio16k_v3"; out.mkdir(parents=True,exist_ok=True); cache.mkdir(parents=True,exist_ok=True)
    if len(SENTENCES)!=150: raise ValueError(f"Expected 150 originals, found {len(SENTENCES)}")
    cp=cache/"manifest.json"
    cm=json.loads(cp.read_text(encoding="utf8")) if cp.exists() else {
        "schema_version":1,"description":"Content-addressed original SAPI WAVs; synthesis parameters included in key","items":{}}
    clips=[]; base=[]
    with tempfile.TemporaryDirectory(prefix="wp21-") as td:
        tmp=Path(td); helper=tmp/"sapi.ps1"; helper.write_text(PS,encoding="utf8")
        for i,text in enumerate(SENTENCES):
            for vi,voice in enumerate(VOICES):
                seed=SEED+i*17+vi
                rng=np.random.default_rng(seed)
                rate=int(rng.integers(-4,5)); volume=int(rng.integers(65,101))
                speech=cache_speech(text,voice,rate,volume,root,cache,helper,tmp,cm)
                cid=f"v3_clean_{i+1:03d}_{vi}"
                path=out/(cid+".wav"); digest=write_wav(path,speech)
                clip={"clip_id":cid,"set":"natural_v3","category":"clean","transcript":text,
                    "voice":voice,"rate":rate,"volume":volume,"snr_db":None,"condition":"clean",
                    "seed":seed,"sha256":digest,"wav":path.name,"duration_s":len(speech)/SR}
                clips.append(clip); base.append((clip,speech))
        # Forty deterministic acoustic overlays, with exact requested noise SNRs.
        plans=[]
        for color in ("white","pink"):
            for snr in (15,5,0):
                plans.extend((f"{color}_noise_{snr}dB",snr,color) for _ in range(3))
        plans += [("babble_10dB",10,"babble")]*4+[("babble_0dB",0,"babble")]*4
        plans += [("music_loop",None,"music")]*3+[("game_effects",None,"effects")]*3
        plans += [("reverb",None,"reverb")]*3+[("radio_8bit",None,"radio")]*5
        for k,(condition,snr,kind) in enumerate(plans):
            source, speech=base[(k*13+7)%len(base)]
            seed=SEED+90000+k; rng=np.random.default_rng(seed); n=len(speech); t=np.arange(n)/SR
            x=speech.copy()
            if kind in ("white","pink","babble"):
                if kind=="babble":
                    others=[base[(k*13+7+j*37)%len(base)][1] for j in range(1,5)]
                    bg=np.zeros(n,np.float32)
                    for j,z in enumerate(others):
                        start=int((j+1)*n/6); z=np.roll(np.resize(z,n),start); bg+=z/4
                else: bg=noise(n,seed,kind=="pink")
                rms=float(np.sqrt(np.mean(speech.astype(np.float64)**2)))
                bg=norm(bg)*rms/(10**(snr/20)); x=speech+bg
            elif kind=="music":
                freqs=[110,164.81,220,329.63]; bg=sum(np.sin(2*np.pi*f*t+idx)*(.02/(idx+1)) for idx,f in enumerate(freqs))
                x=speech+bg.astype(np.float32)
            elif kind=="effects":
                bg=np.zeros(n,np.float32)
                for at in (.2,.55,.82):
                    lo=int(at*n); m=min(int(.12*SR),n-lo)
                    if m>0:bg[lo:lo+m]+=(.3*np.exp(-np.arange(m)/(SR*.025))*rng.normal(size=m)).astype(np.float32)
                x=speech+bg
            elif kind=="reverb":
                length=min(int(rng.uniform(.3,1.2)*SR),int(1.2*SR))
                ir=np.zeros(length,np.float32); ir[0]=1
                ir[1:]=rng.normal(size=length-1)*np.exp(-np.arange(1,length)/(length/5))*0.12
                x=np.convolve(speech,ir)[:n].astype(np.float32)
            elif kind=="radio":
                x=sosfilt(butter(4,[300,3400],btype="bandpass",fs=SR,output="sos"),speech).astype(np.float32)
                q=np.round(np.clip(x,-1,1)*127)/127
                x=(q+noise(n,seed+1)*.002).astype(np.float32)
            cid=f"v3_condition_{k+1:03d}"; path=out/(cid+".wav"); digest=write_wav(path,x)
            clips.append({"clip_id":cid,"set":"natural_v3","category":condition,"transcript":source["transcript"],
                "voice":source["voice"],"rate":source["rate"],"volume":source["volume"],"snr_db":snr,
                "condition":condition,"seed":seed,"sha256":digest,"wav":path.name,"duration_s":n/SR})
        # Five classes × eight durations = 40: silence/dither, room tone, music, effects, unintelligible noise.
        for j,sec in enumerate((2,3,5,8,10,15,20,30)):
            for ci,kind in enumerate(("silence_dither","room_tone","music_only","effects_only","babble_noise_only")):
                seed=SEED+200000+j*5+ci; n=sec*SR; t=np.arange(n)/SR; r=np.random.default_rng(seed)
                if kind=="silence_dither": a=r.uniform(-10**(-70/20),10**(-70/20),n).astype(np.float32)
                elif kind=="room_tone": a=(noise(n,seed)*10**(-48/20)).astype(np.float32)
                elif kind=="music_only": a=(.025*np.sin(2*np.pi*110*t)+.018*np.sin(2*np.pi*164.81*t)).astype(np.float32)
                elif kind=="effects_only":
                    a=np.zeros(n,np.float32)
                    for at in (.2,.45,.7,.9):
                        lo=int(at*n); m=min(int(.15*SR),n-lo)
                        if m>0:a[lo:lo+m]+=(.22*np.exp(-np.arange(m)/(SR*.03))*r.normal(size=m)).astype(np.float32)
                else:
                    a=np.zeros(n,np.float32)
                    for voice_i in range(5):
                        a+=noise(n,seed+voice_i,voice_i%2==0)*.012
                cid=f"v3_nonspeech_{kind}_{sec:02d}s"; path=out/(cid+".wav"); digest=write_wav(path,a)
                clips.append({"clip_id":cid,"set":"natural_v3","category":"non_speech_"+kind,"transcript":"",
                    "voice":None,"rate":None,"volume":None,"snr_db":None,"condition":kind,"seed":seed,
                    "sha256":digest,"wav":path.name,"duration_s":sec})
    manifest={"schema_version":3,"seed":SEED,"sample_rate_hz":SR,"channels":1,"dtype":"float32",
        "transcript_normalization":"Transcript is exactly the authored spoken-form text; numbers are written as words (no digits), punctuation and contractions retained; score case-insensitively after standard punctuation removal. Names are pronounced as spelled in their text.",
        "target_words":["banana","cobalt","harbor"],"distractors":["cobol","arbor","bandana"],
        "voices":list(VOICES),"clips":clips}
    (out/"ground_truth_v3.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    with (out/"clip_list_v3.tsv").open("w",encoding="utf8",newline="") as f:
        f.write("clip_id\tcategory\ttranscript\tvoice\trate\tvolume\tsnr_db\tcondition\tseed\tduration_s\twav\tsha256\n")
        for c in clips:
            vals=[c.get(k) for k in ("clip_id","category","transcript","voice","rate","volume","snr_db","condition","seed","duration_s","wav","sha256")]
            f.write("\t".join("" if x is None else str(x).replace("\t"," ").replace("\n"," ") for x in vals)+"\n")
    durations={}
    for c in clips:
        d=durations.setdefault(c["category"],[0,0]); d[0]+=1; d[1]+=c["duration_s"]
    print(json.dumps({"clips":len(clips),"duration_s":sum(c["duration_s"] for c in clips),
        "conditions":durations,"manifest":str(out/"ground_truth_v3.json")},indent=2))
if __name__=="__main__": main()
