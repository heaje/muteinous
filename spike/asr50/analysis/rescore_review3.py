import json,pathlib,re,unicodedata,math,statistics,collections,sys
sys.path.insert(0,r'C:\code\muteinous-spike50\spike\asr50\benchmark')
import score
R=pathlib.Path(r'C:\scratch\asr50'); GT=json.load(open(R/'corpus_v2_frozen'/'ground_truth_v2.json',encoding='utf8'))['clips']; gt={x['clip_id']:x for x in GT}
base=R/'results_v2'; rows=[]
for runner in ['whispercpp','sherpa-parakeet','faster-whisper','moonshine-onnx','ort-whisper-turbo','ort-whisper-small-en']:
 for dr in sorted((base/runner).iterdir()):
  if not dr.is_dir() or dr.name=='policy-off':continue
  rec=[]
  for clip in GT:
   p=dr/(clip['clip_id']+'.json')
   if p.exists(): rec.append((clip,json.load(open(p,encoding='utf8'))))
  if len(rec)!=60: continue
  S=D=I=N=0; rt=ht=tp=0; silwords=silclips=sildur=0; unfiltered=[]
  for c,d in rec:
   h=score.tokenize(d.get('text','')); ref=score.tokenize(c['transcript'])
   # Silence marker explicitly lexical tokenizer behavior recorded
   if c['set']=='timing' or c['transcript'].strip():
    z=score.edit_counts(ref,h);S+=z['substitutions'];D+=z['deletions'];I+=z['insertions'];N+=len(ref)
   tar=score.target_metrics(c['transcript'],d.get('text',''));rt+=tar['true_positives']+tar['false_negatives'];ht+=tar['true_positives']+tar['false_positives'];tp+=tar['true_positives']
   if c['category'] in ('silence','non_speech'):
    silwords+=len(h);silclips+=bool(h);sildur+=c['duration_s']
  rows.append((runner,dr.name,f'{(S+D+I)/N:.5f}',f'{S}/{D}/{I}',f'{tp/ht if ht else 1:.4f}/{tp/rt if rt else 1:.4f}',f'{silwords*60/sildur:.3f}',f'{silclips}/20'))
print('LEX');[print('\t'.join(x)) for x in rows]
# Timing configs native
configs=[]
for p in (base/'whispercpp').iterdir():
 if p.name.endswith(('-dtw','-ml1')): configs.append(('whispercpp',p))
for p in (base/'faster-whisper').iterdir(): configs.append(('faster-whisper',p))
configs += [('sherpa-parakeet',base/'sherpa-parakeet'/'cpu')]

def tokens(w): return score.tokenize(w.get('word',w.get('text','')))
def match(a,b):
 # independent Levenshtein exact matches, deterministic diag/delete/insert
 return score.edit_counts([tokens(x)[0] if tokens(x) else '' for x in a],[tokens(x)[0] if tokens(x) else '' for x in b])['matches']
def summarize(vals):
 if not vals:return 'n=0'
 s=sorted(vals);return f'n={len(vals)} mean={statistics.mean(vals):.1f} med={statistics.median(vals):.1f} p95={s[math.ceil(.95*len(s))-1]:.1f} <=50/100/200={sum(x<=50 for x in vals)/len(vals):.3f}/{sum(x<=100 for x in vals)/len(vals):.3f}/{sum(x<=200 for x in vals)/len(vals):.3f}'
print('TIMING')
for typ,p in configs:
 for endrule in (['default','duration'] if typ=='sherpa-parakeet' else ['default']):
  starts=[];ends=[];miss=0;hypn=0;pairs=0
  for c in GT:
   if c['set']!='timing':continue
   f=p/(c['clip_id']+'.json')
   if not f.exists():continue
   d=json.load(open(f,encoding='utf8')); h=d.get('words',[])
   if endrule=='duration':h=d.get('words_duration_end',h)
   hypn+=len(h)
   ref=[{'text':w['text']} for w in c['words']]
   for ri,hi in match(ref,h):
    rw=c['words'][ri]; hw=h[hi]; st=hw.get('start',hw.get('start_s')); en=hw.get('end',hw.get('end_s'))
    if st is not None and en is not None:
     starts.append(abs(st-rw['start_sample']/16000)*1000);ends.append(abs(en-rw['end_sample']/16000)*1000);pairs+=1
   miss+=sum(1 for w in h if w.get('start',w.get('start_s')) is None or w.get('end',w.get('end_s')) is None)
  if pairs:print(f'{typ}\t{p.name}\t{endrule}\tpairs={pairs} miss={miss}/{hypn}\tSTART {summarize(starts)}\tEND {summarize(ends)}')
