#!/usr/bin/env python3
"""Synchronise le contrat depuis un clone frère du frontend.

    uv run tools/contrat_sync.py [../synelia-cloud]

- copie `docs/api/openapi.json` → `packages/contract/synelia_contract/openapi.json`
- exporte workflows, RBAC, configurations en JSON (tsx côté frontend)
- régénère `modeles.py` (datamodel-codegen) et `operations.py` (index des opérations)
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
CONTRAT = RACINE / "packages" / "contract" / "synelia_contract"
CATALOGUE = RACINE / "packages" / "catalogue" / "synelia_catalogue"


def snake(s: str) -> str:
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", s)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s).lower()


def nom_inline(chemin: str, methode: str, suffixe: str) -> str:
    """Nom que datamodel-codegen donne à un schéma inline d'une opération."""
    morceaux = []
    for seg in chemin.strip("/").split("/"):
        seg = seg.strip("{}")
        for part in re.split(r"[-_]", seg):
            morceaux.append(part[:1].upper() + part[1:])
    return "".join(morceaux) + methode.capitalize() + suffixe


def ref_name(schema: dict | None) -> str | None:
    if not schema:
        return None
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if schema.get("type") == "array" and "$ref" in schema.get("items", {}):
        return "list[" + schema["items"]["$ref"].rsplit("/", 1)[-1] + "]"
    return None


def generer_operations(spec: dict) -> str:
    lignes = [
        '"""GÉNÉRÉ par tools/contrat_sync.py — ne pas éditer.',
        "",
        "Index des opérations du contrat : méthode, chemin, operationId, action RBAC,",
        'codes de réponse déclarés, schéma du corps et schéma de la réponse principale."""',
        "",
        "from __future__ import annotations",
        "",
        "from dataclasses import dataclass, field",
        "",
        "",
        "@dataclass(frozen=True)",
        "class Operation:",
        "    methode: str",
        "    chemin: str",
        "    operation_id: str",
        "    nom_python: str",
        "    tag: str",
        "    rbac: str | None",
        "    securite: bool",
        "    codes: tuple[str, ...]",
        "    code_succes: int",
        "    corps: str | None",
        "    reponse: str | None",
        "    corps_modele: str | None",
        "    reponse_modele: str | None",
        "    parametres_chemin: tuple[str, ...] = field(default_factory=tuple)",
        "    parametres_requete: tuple[str, ...] = field(default_factory=tuple)",
        "",
        "",
        "OPERATIONS: tuple[Operation, ...] = (",
    ]
    params_communs = spec["components"].get("parameters", {})
    for chemin, item in spec["paths"].items():
        for methode, op in item.items():
            if methode not in ("get", "post", "put", "patch", "delete"):
                continue
            codes = tuple(sorted(op.get("responses", {}).keys()))
            succes = min(int(c) for c in codes if c.startswith("2"))
            corps = ref_name(
                op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
            )
            rep = op["responses"].get(str(succes), {})
            reponse = ref_name(rep.get("content", {}).get("application/json", {}).get("schema"))
            a_corps = "application/json" in op.get("requestBody", {}).get("content", {})
            corps_modele = corps if corps else (nom_inline(chemin, methode, "Request") if a_corps else None)
            a_reponse = "application/json" in rep.get("content", {})
            reponse_modele = reponse if reponse else (nom_inline(chemin, methode, "Response") if a_reponse else None)
            pchemin, prequete = [], []
            for p in op.get("parameters", []):
                if "$ref" in p:
                    p = params_communs[p["$ref"].rsplit("/", 1)[-1]]
                (pchemin if p.get("in") == "path" else prequete).append(p["name"])
            securite = op.get("security", [{"bearerAuth": []}]) != []
            lignes.append(
                "    Operation("
                f"{methode.upper()!r}, {chemin!r}, {op['operationId']!r}, {snake(op['operationId'])!r}, "
                f"{(op.get('tags') or ['?'])[0]!r}, {op.get('x-rbac')!r}, {securite!r}, {codes!r}, {succes}, "
                f"{corps!r}, {reponse!r}, {corps_modele!r}, {reponse_modele!r}, {tuple(pchemin)!r}, {tuple(prequete)!r}),"
            )
    lignes += [
        ")",
        "",
        "PAR_ID: dict[str, Operation] = {o.operation_id: o for o in OPERATIONS}",
        "PAR_ROUTE: dict[tuple[str, str], Operation] = {(o.methode, o.chemin): o for o in OPERATIONS}",
        "",
    ]
    return "\n".join(lignes)


def corriger_collisions(fichier: Path, spec: dict) -> None:
    """datamodel-codegen peut donner à un schéma du contrat un nom dérivé (`XModel`, `X1`) quand un
    objet inline porte le même nom. On rend au schéma du contrat son nom exact et on suffixe l'inline."""
    import ast
    import re as _re

    texte = fichier.read_text()
    arbre = ast.parse(texte)
    champs: dict[str, set[str]] = {}
    for n in arbre.body:
        if isinstance(n, ast.ClassDef):
            champs[n.name] = {t.target.id for t in n.body if isinstance(t, ast.AnnAssign) and isinstance(t.target, ast.Name)}
    for nom, schema in spec["components"]["schemas"].items():
        props = set(schema.get("properties", {}))
        if not props or nom not in champs or champs[nom] == props:
            continue
        candidats = [c for c in champs if _re.fullmatch(rf"{nom}(Model|\d+)", c) and champs[c] == props]
        if not candidats:
            continue
        bon = candidats[0]
        texte = _re.sub(rf"\b{nom}\b", f"{nom}Inline", texte)
        texte = _re.sub(rf"\b{bon}\b", nom, texte)
        champs[f"{nom}Inline"] = champs.pop(nom)
        champs[nom] = champs.pop(bon)
    fichier.write_text(texte)


def main() -> int:
    frontend = Path(sys.argv[1] if len(sys.argv) > 1 else RACINE.parent / "synelia-cloud").resolve()
    source = frontend / "docs" / "api" / "openapi.json"
    if not source.exists():
        print(f"contrat introuvable : {source}", file=sys.stderr)
        return 1
    CONTRAT.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, CONTRAT / "openapi.json")
    spec = json.loads(source.read_text())
    print(f"openapi.json copié : {len(spec['paths'])} chemins, {len(spec['components']['schemas'])} schémas")

    tsx = shutil.which("tsx") or str(Path.home() / ".local" / "bin" / "tsx")
    subprocess.run([tsx, str(RACINE / "tools" / "exporter_frontend.mts"), str(frontend), str(CONTRAT)], check=True)
    CATALOGUE.mkdir(parents=True, exist_ok=True)
    shutil.move(str(CONTRAT / "configurations.json"), CATALOGUE / "configurations.json")

    (CONTRAT / "operations.py").write_text(generer_operations(spec))
    print("operations.py généré")

    subprocess.run(
        [
            "datamodel-codegen",
            "--input", str(CONTRAT / "openapi.json"),
            "--input-file-type", "openapi",
            "--output", str(CONTRAT / "modeles.py"),
            "--output-model-type", "pydantic_v2.BaseModel",
            "--use-annotated",
            "--field-constraints",
            "--use-standard-collections",
            "--use-union-operator",
            "--use-schema-description",
            "--target-python-version", "3.12",
            "--disable-timestamp",
            "--enum-field-as-literal", "all",
            "--use-default-kwarg",
            "--collapse-root-models",
            "--openapi-scopes", "schemas", "paths",
            "--formatters", "ruff-format",
        ],
        check=True,
    )
    corriger_collisions(CONTRAT / "modeles.py", spec)
    print("modeles.py généré")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
