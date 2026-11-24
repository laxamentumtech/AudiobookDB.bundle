# Person credit parsing shared by the update and search paths.


def collect_role_credits(people, scope_type, scope_id, role_name):
    """
        Returns ordered credits for one role within an entity scope.

        Deduplication uses (scope_type, scope_id, person.id, role) when the
        credit carries a person ID. A name-only credit (SearchDocumentBook
        permits those) falls back to (scope_type, scope_id, name, role) so
        usable display names are never discarded or given invented IDs.
        Payload order is preserved; blank names are dropped.
    """
    credits = []
    seen = set()
    for relation in people or []:
        if not isinstance(relation, dict):
            continue
        person = relation.get('person')
        role = relation.get('role')
        if not isinstance(person, dict) or not isinstance(role, dict):
            continue
        role_name_value = role.get('name')
        person_id = person.get('id')
        name = (person.get('name') or '').strip()
        if role_name_value != role_name or not name:
            continue
        if person_id:
            key = (scope_type, scope_id, 'id', person_id, role_name_value)
        else:
            key = (scope_type, scope_id, 'name', name, role_name_value)
        if key in seen:
            continue
        seen.add(key)
        credit = {'name': name}
        if person_id:
            credit['id'] = person_id
        credits.append(credit)
    return credits
