# Runbook d'astreinte — Pyrenex Prod (À COMPLÉTER)

> Pour l'équipe SRE Pyrenex. Rédigez **4 procédures**. Chacune doit suivre
> le même format : **déclenchement → actions → qui appeler → ce qu'on NE
> fait PAS**. Mini-cours : `05_Runbook_astreinte_essentiel.md`.

---

## 1. Service KO (un conteneur down)

**Déclenchement** : `docker compose ps` montre un service en `exited` ou `unhealthy` pendant plus de 2 minutes, ou le panel « Vie » affiche RPS ≈ 0 pendant > 2 min.

**Actions** :
1. `docker compose logs --tail=100 model` puis `docker compose logs --tail=100 backend` pour lire l’erreur la plus récente.
2. Identifier l'erreur
3. Relance docker compose restart <service> et checker `docker compose ps`

**Qui appeler** : Responsable backend ou infrastructure si le problème est au niveau du docker/compose

**On NE fait PAS** : `docker compose down -v` (détruit les volumes), ni `docker system prune` sans validation. On n’efface pas les données ni les volumes en prod

---

## 2. Latence p95 dégradée

**Déclenchement** : le panel « Vitesse » dépasse le seuil de base : p95 de `/predict` > 300 ms sur 5 minutes

**Actions** :
1. Vérifier le panel Grafana « Vitesse — p50/p95/p99 »
2. `docker stats` pour détecter saturation CPU ou mémoire sur `model` et `backend`
3. Vérifier si un déploiement récent ou un changement de config a eu lieu dans les dernières heures.
4. Si le pic est clair et durable, redémarrer le service concerné puis re-checker la latence 2-3 minutes plus tard.

**Qui appeler** : responsable modèle si la latence vient du calcul lui-même

**On NE fait PAS** : ne pas redéployer une version non validée, ni modifier le code en prod sans test

---

## 3. Métrique modèle qui s'écarte (distribution des prédictions anormale)

**Déclenchement** : la distribution des prédictions `pyrenex_predictions_total` s’écarte sensiblement de la baseline stable, par exemple > 20 points de pourcentage de classe 1 sur 5 min, ou la probabilité moyenne de défaut sort du band de référence.

**Actions** : 
1. Vérifier le panel de comportement modèle (répartition 0/1, distribution de probabilité, p95 de latence).
2. Comparer avec le golden run / la baseline de référence enregistrée dans le projet.
3. Vérifier si un changement de jeu de données, de version de modèle ou de config a été déployé.
4. Si l’écart est confirmé, arrêter la diffusion de cette version et revenir à la dernière version stable.

**Qui appeler** : responsable modèle

**On NE fait PAS** : ne pas “ajuster” les seuils pour faire passer le dashboard, ni contourné le signal par un hotfix sans validation. On ne déploie pas un modèle qui n’a pas été évalué contre le golden run.

---

## 4. Rollback de release

**Déclenchement** : un incident persiste après 2 tentatives, la latence dépasse le seuil critique, la distribution du modèle est anormale, ou un déploiement récent introduit une régression confirmée.


**Actions** : 
1. Identifier la version actuellement déployée et la dernière version stable connue.
2. Revenir au tag/image stable précédent (`docker compose pull` / `docker compose up -d` sur la version précédente ou image tagged stable).
3. Vérifier la santé (`docker compose ps`, `/health`, métriques Grafana) dans les 5 minutes suivantes.
4. Ouvrir le note d’incident pour indiquer la cause et la version restaurée.

**Qui appeler** : responsable projet

**On NE fait PAS** : ne pas bricoler en prod, ne pas faire un “fix rapide” sans validation, et ne pas supprimer les volumes ni des données de production. Le rollback doit être simple, documenté et réversible.


