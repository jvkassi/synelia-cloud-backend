# ADR 0002 — Déploiement Vercel : API seule, travaux exécutés en ligne, amont simulé

Date : 2026-09-03. Statut : accepté.

## Contexte
Le portail est sur Vercel ; l'équipe veut des préversions par branche pour le backend aussi. Vercel n'héberge
ni Temporal, ni Valkey, ni un worker long-vécu, et n'atteint pas le lab OpenStack (réseau privé).

## Décision
- `api/index.py` sert l'application FastAPI ; `vercel.json` réécrit tout vers cette fonction.
- Sans `SYNELIA_DATABASE_URL`, SQLite dans `/tmp` (éphémère par instance) ; avec une URL Postgres (Neon…),
  le plan de contrôle est durable.
- Les travaux (`202`) s'exécutent **en ligne** avant la réponse quand `VERCEL=1` : la réponse porte déjà
  l'état final. Avec `SYNELIA_TEMPORAL_ADRESSE`, le même code délègue à Temporal (worker Docker/Dokploy).
- `SYNELIA_FOURNISSEUR=simule` par défaut : chaque amont a une paire `Simule` / réel ; le réel ne s'active
  qu'avec sa configuration. Vercel = bac à sable fonctionnel du contrat, pas la production IaaS.

## Conséquences
La production reste l'image Docker (`synelia api|worker|scheduler`) sur Dokploy/Kubernetes, près du lab,
avec Postgres + Temporal + Valkey (`docker-compose.yml`). Vercel sert le frontend et les préversions.
