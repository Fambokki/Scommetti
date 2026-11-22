"""Backtest walk-forward del modello di Scommetti sui 5 maggiori campionati.

Per ogni settimana di ogni campionato:
  - il modello di Poisson/Dixon-Coles viene stimato SOLO sulle partite giocate prima (finestra di ~2 stagioni,
    stesso decadimento e stessa regolarizzazione dell'app);
  - l'Elo pre-partita (clubelo) viene trasformato in 1X2 con un modello logit ordinato stimato sulle stagioni precedenti;
  - il mercato è la media delle quote dei bookmaker, senza margine.
Poi si misurano log-loss, Brier, accuratezza e calibrazione; i pesi del mix vengono scelti sulle stagioni di
addestramento e verificati su quelle successive; infine si simulano le giocate.
"""
import json, math, sys
import numpy as np, pandas as pd

LEAGUES = {'I1': 'Serie A', 'E0': 'Premier League', 'SP1': 'LaLiga', 'D1': 'Bundesliga', 'F1': 'Ligue 1'}
FIRST_TEST, TRAIN_END, LAST = 2007, 2015, 2025          # stagioni (anno di inizio)

d = pd.read_csv('data/m.csv', low_memory=False)
d = d[d.Division.isin(LEAGUES)].copy()
d['date'] = pd.to_datetime(d.MatchDate)
d['season'] = d.date.dt.year - (d.date.dt.month < 7)
late = (d.date >= '2020-07-01') & (d.date < '2020-08-10')        # fine stagione 2019/20 spostata dal Covid
d.loc[late, 'season'] = 2019
d = d[(d.season >= 2005) & (d.season <= LAST)]
d = d.dropna(subset=['FTHome', 'FTAway', 'OddHome', 'OddDraw', 'OddAway', 'HomeElo', 'AwayElo'])
d['hg'] = d.FTHome.astype(int); d['ag'] = d.FTAway.astype(int)
d['res'] = np.where(d.hg > d.ag, 0, np.where(d.hg == d.ag, 1, 2))
d = d.sort_values('date').reset_index(drop=True)

# ---------- modello di Poisson con correzione Dixon-Coles (identico all'app) ----------
XI, K, RHO = 0.0045, 3.0, -0.08
fact = np.array([math.factorial(i) for i in range(11)], float)

def fit(hist, now, cur_season):
    teams = pd.unique(pd.concat([hist.HomeTeam, hist.AwayTeam]))
    ix = {t: i for i, t in enumerate(teams)}; n = len(teams)
    h = hist.HomeTeam.map(ix).to_numpy(); a = hist.AwayTeam.map(ix).to_numpy()
    hg = hist.hg.to_numpy(float); ag = hist.ag.to_numpy(float)
    w = np.exp(-XI * np.maximum(0, (now - hist.date).dt.days.to_numpy()))
    cur = set(hist[hist.season == cur_season][['HomeTeam', 'AwayTeam']].stack())
    prev = set(hist[hist.season < cur_season][['HomeTeam', 'AwayTeam']].stack())
    a0 = np.ones(n); d0 = np.ones(n)
    for t, i in ix.items():
        if t in cur and t not in prev and prev: a0[i], d0[i] = 0.82, 1.18
    A = np.ones(n); D = np.full(n, 1.3); g = 1.25
    for _ in range(60):
        dbar = D.mean(); u = dbar * (1 + g) / 2
        nA = np.bincount(h, w * hg, n) + np.bincount(a, w * ag, n)
        dA = np.bincount(h, w * D[a] * g, n) + np.bincount(a, w * D[h], n)
        A = (nA + K * a0 * u) / (dA + K * u)
        nD = np.bincount(a, w * hg, n) + np.bincount(h, w * ag, n)
        dD = np.bincount(a, w * A[h] * g, n) + np.bincount(h, w * A[a], n)
        v = (1 + g) / 2
        D = (nD + K * d0 * dbar * v) / (dD + K * v)
        g = (w * hg).sum() / (w * A[h] * D[a]).sum()
        m = A.mean(); A /= m; D *= m
    return ix, A, D, g

def predict(model, ht, at):
    ix, A, D, g = model
    if ht not in ix or at not in ix: return None
    lh = A[ix[ht]] * D[ix[at]] * g; la = A[ix[at]] * D[ix[ht]]
    i = np.arange(11)
    ph = np.exp(-lh) * lh ** i / fact; pa = np.exp(-la) * la ** i / fact
    M = np.outer(ph, pa)
    M[0, 0] *= 1 - lh * la * RHO; M[0, 1] *= 1 + lh * RHO; M[1, 0] *= 1 + la * RHO; M[1, 1] *= 1 - RHO
    M /= M.sum()
    p1 = np.tril(M, -1).sum(); px = np.trace(M); p2 = np.triu(M, 1).sum()
    ov = M[np.add.outer(i, i) > 2].sum()
    return p1, px, p2, ov

# ---------- Elo -> 1X2 con logit ordinato (stimato sulle stagioni precedenti) ----------
def fit_elo(df):
    x = (df.HomeElo - df.AwayElo).to_numpy() / 100; y = df.res.to_numpy()
    b, c1, c2 = 0.4, -0.3, 0.6          # P(2)=s(c1-z) , P(2 o X)=s(c2-z), z=b*x+hadv
    params = np.array([b, c1, c2])
    def nll(p):
        b, c1, c2 = p
        if c2 <= c1: return 1e9
        z = b * x
        s1 = 1 / (1 + np.exp(-(c1 - z))); s2 = 1 / (1 + np.exp(-(c2 - z)))
        pr = np.stack([1 - s2, s2 - s1, s1], 1)
        return -np.log(np.clip(pr[np.arange(len(y)), y], 1e-12, 1)).sum()
    # discesa a coordinate semplice
    step = np.array([0.1, 0.1, 0.1]); best = nll(params)
    for _ in range(200):
        imp = False
        for j in range(3):
            for s in (+1, -1):
                q = params.copy(); q[j] += s * step[j]; v = nll(q)
                if v < best: best, params, imp = v, q, True
        if not imp: step /= 2
        if step.max() < 1e-4: break
    return params

def elo_probs(p, dh, da):
    b, c1, c2 = p; z = b * (dh - da) / 100
    s1 = 1 / (1 + math.exp(-(c1 - z))); s2 = 1 / (1 + math.exp(-(c2 - z)))
    return 1 - s2, s2 - s1, s1          # 1, X, 2

# ---------- walk-forward ----------
rows = []
elo_par = {}
for season in range(FIRST_TEST, LAST + 1):
    elo_par[season] = fit_elo(d[(d.season < season) & (d.season >= season - 4)])
for lg in LEAGUES:
    L = d[d.Division == lg]
    for season in range(FIRST_TEST, LAST + 1):
        S = L[L.season == season]
        weeks = S.date.dt.to_period('W')
        for wk in weeks.unique():
            G = S[weeks == wk]
            start = G.date.min()
            hist = L[(L.date < start) & (L.date >= start - pd.Timedelta(days=730))]
            if len(hist) < 200: continue
            model = fit(hist, start, season)
            for r in G.itertuples():
                pm = predict(model, r.HomeTeam, r.AwayTeam)
                if pm is None: continue
                pe = elo_probs(elo_par[season], r.HomeElo, r.AwayElo)
                inv = np.array([1 / r.OddHome, 1 / r.OddDraw, 1 / r.OddAway]); pk = inv / inv.sum()
                rows.append(dict(lg=lg, season=season, date=str(r.date.date()), home=r.HomeTeam, away=r.AwayTeam, res=r.res,
                                 m1=pm[0], mx=pm[1], m2=pm[2], mov=pm[3],
                                 e1=pe[0], ex=pe[1], e2=pe[2], k1=pk[0], kx=pk[1], k2=pk[2], margin=inv.sum() - 1,
                                 o1=r.OddHome, ox=r.OddDraw, o2=r.OddAway,
                                 x1=r.MaxHome, xx=r.MaxDraw, x2=r.MaxAway,
                                 over=float(r.hg + r.ag > 2), oo=r.Over25, ou=r.Under25))
    print(lg, len(rows), file=sys.stderr)
P = pd.DataFrame(rows)
P.to_csv('preds.csv', index=False)
print('partite previste:', len(P))
