import json, numpy as np, pandas as pd
P = pd.read_csv('preds.csv')
Y = np.eye(3)[P.res.to_numpy()]
SRC = {'Modello (Poisson)': P[['m1', 'mx', 'm2']].to_numpy(), 'Elo': P[['e1', 'ex', 'e2']].to_numpy(),
       'Mercato (quote)': P[['k1', 'kx', 'k2']].to_numpy()}
train = (P.season <= 2015).to_numpy(); test = ~train

def metrics(p, m):
    p = np.clip(p[m], 1e-9, 1); y = Y[m]
    return dict(logloss=float(-(y * np.log(p)).sum(1).mean()), brier=float(((p - y) ** 2).sum(1).mean()),
                acc=float((p.argmax(1) == y.argmax(1)).mean()), n=int(m.sum()))

def blend(w):
    w = np.array(w) / sum(w)
    return w[0] * SRC['Modello (Poisson)'] + w[1] * SRC['Elo'] + w[2] * SRC['Mercato (quote)']

out = {'n_total': len(P), 'seasons': [int(P.season.min()), int(P.season.max())], 'per_league': P.groupby('lg').size().to_dict()}
out['base'] = {'Frequenze storiche (sempre 46/27/27)': None}
freq = Y[train].mean(0); base = np.tile(freq, (len(P), 1))
out['metrics'] = {'Nessun modello (solo frequenze)': {'train': metrics(base, train), 'test': metrics(base, test)}}
for k, v in SRC.items(): out['metrics'][k] = {'train': metrics(v, train), 'test': metrics(v, test)}
cur = blend([0.30, 0.25, 0.45]); out['metrics']['Mix attuale dell\'app 30/25/45'] = {'train': metrics(cur, train), 'test': metrics(cur, test)}

# ricerca dei pesi sulle stagioni di addestramento
best = None; grid = []
for a in range(0, 21):
    for b in range(0, 21 - a):
        c = 20 - a - b; w = (a / 20, b / 20, c / 20)
        ll = metrics(blend(w), train)['logloss']; grid.append((w, ll))
        if best is None or ll < best[1]: best = (w, ll)
W = best[0]
opt = blend(W)
out['weights'] = {'model': W[0], 'elo': W[1], 'market': W[2]}
out['metrics']['Mix ottimizzato'] = {'train': metrics(opt, train), 'test': metrics(opt, test)}

# correzione del pareggio (il modello tende a sbagliare la X?) + calibrazione per fasce
def calib(p, m, k):
    bins = np.linspace(0, 1, 11); q = p[m][:, k]; y = Y[m][:, k]; r = []
    for i in range(10):
        s = (q >= bins[i]) & (q < bins[i + 1])
        if s.sum() >= 50: r.append(dict(lo=float(bins[i]), hi=float(bins[i + 1]), pred=float(q[s].mean()), real=float(y[s].mean()), n=int(s.sum())))
    return r
out['calibration'] = {lbl: calib(opt, test, k) for k, lbl in enumerate(['1', 'X', '2'])}
allq = np.concatenate([opt[test][:, k] for k in range(3)]); ally = np.concatenate([Y[test][:, k] for k in range(3)])
bins = np.linspace(0, 1, 11); cal = []
for i in range(10):
    s = (allq >= bins[i]) & (allq < bins[i + 1])
    if s.sum() >= 50: cal.append(dict(lo=float(bins[i]), hi=float(bins[i + 1]), pred=float(allq[s].mean()), real=float(ally[s].mean()), n=int(s.sum())))
out['calibration_all'] = cal

# precisione per campionato e per stagione (mix ottimizzato, test)
out['by_league'] = {lg: {**metrics(opt, test & (P.lg == lg).to_numpy()), 'market': metrics(SRC['Mercato (quote)'], test & (P.lg == lg).to_numpy())['logloss']} for lg in P.lg.unique()}
out['by_season'] = {int(s): {'opt': metrics(opt, (P.season == s).to_numpy())['logloss'], 'market': metrics(SRC['Mercato (quote)'], (P.season == s).to_numpy())['logloss'],
                             'model': metrics(SRC['Modello (Poisson)'], (P.season == s).to_numpy())['logloss'], 'acc': metrics(opt, (P.season == s).to_numpy())['acc']} for s in sorted(P.season.unique())}

# accuratezza dei "più probabili" per fascia di sicurezza
fav = opt.max(1); hit = (opt.argmax(1) == P.res.to_numpy())
out['fav_bands'] = [dict(lo=lo, hi=hi, n=int(((fav >= lo) & (fav < hi) & test).sum()), pred=float(fav[(fav >= lo) & (fav < hi) & test].mean()), hit=float(hit[(fav >= lo) & (fav < hi) & test].mean()))
                    for lo, hi in [(0.33, .45), (.45, .55), (.55, .65), (.65, .75), (.75, 1.0)]]

# ---------- simulazione delle giocate (stagioni di verifica) ----------
odds_avg = P[['o1', 'ox', 'o2']].to_numpy(); odds_max = P[['x1', 'xx', 'x2']].to_numpy()
def simulate(prob, odds, edge, m, stake='flat', kf=1/3, cap=0.05, minp=0.15):
    ev = prob * odds; ok = np.isfinite(odds) & (odds > 1)
    ev = np.where(ok, ev, 0)
    pick = ev.argmax(1); best = ev.max(1); pp = prob[np.arange(len(prob)), pick]
    sel = m & (best >= 1 + edge) & (pp >= minp)
    o = odds[np.arange(len(prob)), pick]; won = (pick == P.res.to_numpy())
    if stake == 'flat':
        st = np.where(sel, 1.0, 0)
        prof = np.where(sel, np.where(won, o - 1, -1), 0)
        n = int(sel.sum()); return dict(bets=n, staked=float(st.sum()), profit=float(prof.sum()), roi=float(prof.sum() / max(1, n)), hit=float(won[sel].mean()) if n else 0,
                                        avg_odds=float(o[sel].mean()) if n else 0)
    # Kelly frazionato, giocate in ordine di data, cassa 1000
    bank = 1000.0; peak = bank; mdd = 0; curve = []
    order = np.argsort(P.date.to_numpy(), kind='stable')
    for i in order:
        if not sel[i]: continue
        f = min(cap, kf * (pp[i] * o[i] - 1) / (o[i] - 1))
        s = bank * f; bank += s * (o[i] - 1) if won[i] else -s
        peak = max(peak, bank); mdd = max(mdd, 1 - bank / peak); curve.append(bank)
    return dict(bets=int(sel.sum()), final=bank, max_drawdown=mdd, curve=curve[::max(1, len(curve) // 200)])

sims = {}
for name, odds in [('quote medie', odds_avg), ('quota migliore', odds_max)]:
    for edge in [0.0, 0.015, 0.03, 0.05, 0.10]:
        sims[f'{name}|{edge}'] = simulate(opt, odds, edge, test)
out['sims'] = sims
out['sims_model_only'] = {f'{n}|{e}': simulate(SRC['Modello (Poisson)'], o, e, test) for n, o in [('quote medie', odds_avg), ('quota migliore', odds_max)] for e in [0.03, 0.05, 0.10]}
out['kelly'] = {f'{n}|{e}': simulate(opt, o, e, test, 'kelly') for n, o in [('quote medie', odds_avg), ('quota migliore', odds_max)] for e in [0.03, 0.05]}
# strategie semplici di confronto
favpick = opt.argmax(1); fo = odds_avg[np.arange(len(P)), favpick]; fw = favpick == P.res.to_numpy()
out['baseline_fav'] = dict(bets=int(test.sum()), roi=float(np.where(fw, fo - 1, -1)[test].mean()), hit=float(fw[test].mean()))
mk = SRC['Mercato (quote)'].argmax(1); mo = odds_avg[np.arange(len(P)), mk]; mw = mk == P.res.to_numpy()
out['baseline_bookfav'] = dict(roi=float(np.where(mw, mo - 1, -1)[test].mean()), hit=float(mw[test].mean()))
dr = odds_avg[:, 1]; out['baseline_draw'] = dict(roi=float(np.where(P.res.to_numpy() == 1, dr - 1, -1)[test].mean()))
out['avg_margin'] = float(P.margin[test].mean())
# multiple: probabilità reale e resa di multiple da 2/3/4/5 dei favoriti per giornata (campione)
rng = np.random.default_rng(7); multi = {}
ti = np.where(test)[0]
for n in [2, 3, 4, 5, 8]:
    res = []; rois = []
    for _ in range(20000):
        idx = rng.choice(ti, n, replace=False)
        q = fo[idx].prod(); w = fw[idx].all(); res.append(w); rois.append(q - 1 if w else -1)
    multi[n] = dict(hit=float(np.mean(res)), roi=float(np.mean(rois)))
out['multiples_fav'] = multi
json.dump(out, open('results.json', 'w'), indent=1, default=float)
print(json.dumps({k: out[k] for k in ['weights', 'metrics', 'baseline_fav', 'baseline_bookfav', 'avg_margin', 'multiples_fav']}, indent=1))
for k, v in sims.items(): print(k, {x: round(y, 4) if isinstance(y, float) else y for x, y in v.items()})
for k, v in out['sims_model_only'].items(): print('MODEL', k, {x: round(y, 4) if isinstance(y, float) else y for x, y in v.items()})
for k, v in out['kelly'].items(): print('KELLY', k, {x: (round(y, 3) if isinstance(y, float) else y) for x, y in v.items() if x != 'curve'})
print(out['fav_bands'])
print(out['calibration_all'])
