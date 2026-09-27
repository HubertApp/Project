"""
Parcours joués dans l'ordre de cette liste.

Pour ajouter un parcours : créer un module avec des fonctions décorées par
`@step`, qui n'envoient que des requêtes de fronts (front_ops.call), puis
l'ajouter ici.
"""

SCENARIOS = [
    "scenarios.p0_precheck",
    "scenarios.ad_admin",
    "scenarios.us_user",
]
