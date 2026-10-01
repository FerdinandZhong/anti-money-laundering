"""Read-only graph projection of the published AML semantic model."""

from semantic.model_loader import ontology, semantic_model


def model_graph() -> dict:
    """Keep visualized edges tied to declared Ossie-style field relationships."""
    source = semantic_model()
    concepts = ontology()
    model = (source.get("semantic_model") or [{}])[0]
    datasets = model.get("datasets") or []
    names = {item["name"] for item in datasets if item.get("name")}
    nodes = [
        {
            "id": item["name"],
            "label": item["name"].replace("_", " ").title(),
            "source": item.get("source", ""),
            "description": item.get("description", ""),
            "primary_key": item.get("primary_key") or [],
            "fields": [
                {"name": field["name"], "description": field.get("description", "")}
                for field in item.get("fields") or [] if field.get("name")
            ],
        }
        for item in datasets if item.get("name")
    ]
    edges = []
    for relation in model.get("relationships") or []:
        origin, target = relation.get("from", ""), relation.get("to", "")
        from_dataset, _, _ = origin.partition(".")
        to_dataset, _, _ = target.partition(".")
        if from_dataset not in names or to_dataset not in names:
            continue
        edges.append({
            "id": relation["name"],
            "source": from_dataset,
            "target": to_dataset,
            "from_field": origin,
            "to_field": target,
            "description": relation.get("description", ""),
        })
    return {
        "version": source.get("version"),
        "model": model.get("name"),
        "nodes": nodes,
        "edges": edges,
        "metrics": [
            {"id": item["name"], "description": item.get("description", "")}
            for item in model.get("metrics") or [] if item.get("name")
        ],
        "ontology": {
            "version": concepts.get("ontology_version"),
            "concepts": [
                {"id": item["id"], "label": item.get("label", item["id"]),
                 "definition": item.get("definition", ""),
                 "synonyms": item.get("synonyms") or []}
                for item in concepts.get("concepts") or [] if item.get("id")
            ],
            "relations": [
                {"id": item["id"], "source": item["from"], "target": item["to"],
                 "description": item.get("definition", "")}
                for item in concepts.get("relations") or []
                if item.get("id") and item.get("from") and item.get("to")
            ],
        },
    }
