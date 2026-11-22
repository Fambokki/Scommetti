import json,numpy as np,pandas as pd
P=pd.read_csv('preds.csv');Y=np.eye(3)[P.res.to_numpy()];test=(P.season>2015).to_numpy();train=~test
M=P[['m1','mx','m2']].to_numpy();E=P[['e1','ex','e2']].to_numpy();K=P[['k1','kx','k2']].to_numpy()
ll=lambda p,m:float(-(Y[m]*np.log(np.clip(p[m],1e-9,1))).sum(1).mean())
o=json.load(open('results.json'))
# pesi fini
res=[]
for wm in np.arange(0,0.31,0.02):
  for we in np.arange(0,0.31-wm,0.02):
    p=wm*M+we*E+(1-wm-we)*K;res.append((round(wm,2),round(we,2),ll(p,train),ll(p,test)))
r=sorted(res,key=lambda x:x[2])[:5];print('fine',r)
# senza quote: miglior mix modello/elo
r2=[(w,ll(w*M+(1-w)*E,train),ll(w*M+(1-w)*E,test)) for w in np.arange(0,1.01,0.05)];b=min(r2,key=lambda x:x[1]);print('noodds',b)
o['weights_fine']=dict(model=r[0][0],elo=r[0][1],market=round(1-r[0][0]-r[0][1],2),train=r[0][2],test=r[0][3])
o['weights_noodds']=dict(model=round(b[0],2),elo=round(1-b[0],2),train=b[1],test=b[2])
# roi per stagione: mercato vs quota migliore, margine 5%
X=P[['x1','xx','x2']].to_numpy();ev=np.where(np.isfinite(X),K*X,0);pk=ev.argmax(1);bv=ev.max(1);pp=K[np.arange(len(P)),pk]
won=pk==P.res.to_numpy();o_=X[np.arange(len(P)),pk]
ps={}
for s in sorted(P.season.unique()):
  m=(P.season==s).to_numpy()&(bv>=1.05)&(pp>=0.15)
  ps[int(s)]=dict(bets=int(m.sum()),roi=float(np.where(won,o_-1,-1)[m].mean()) if m.sum() else None)
o['roi_by_season_max5']=ps;print(ps)
# mix attuale dell'app contro quota migliore
cur=0.3*M+0.25*E+0.45*K
for name,p in [('mix attuale',cur),('mercato',K)]:
  ev=np.where(np.isfinite(X),p*X,0);pk=ev.argmax(1);bv=ev.max(1);pp=p[np.arange(len(P)),pk];w=pk==P.res.to_numpy();oo=X[np.arange(len(P)),pk]
  for e in [0.03,0.05]:
    m=test&(bv>=1+e)&(pp>=0.15);o.setdefault('cmp',{})[f'{name}|{e}']=dict(bets=int(m.sum()),roi=float(np.where(w,oo-1,-1)[m].mean()))
print(o['cmp'])
# come si distribuiscono le giocate con valore per segno
ev=np.where(np.isfinite(X),K*X,0);pk=ev.argmax(1);bv=ev.max(1);pp=K[np.arange(len(P)),pk];m=test&(bv>=1.05)&(pp>=0.15)
o['value_by_sign']={s:int(((pk==i)&m).sum()) for i,s in enumerate(['1','X','2'])};print(o['value_by_sign'])
# per campionato roi max5
o['roi_by_league_max5']={lg:float(np.where(won,o_-1,-1)[test&(P.lg==lg).to_numpy()&(bv>=1.05)&(pp>=0.15)].mean()) for lg in P.lg.unique()};print(o['roi_by_league_max5'])
json.dump(o,open('results.json','w'),indent=1,default=float)
