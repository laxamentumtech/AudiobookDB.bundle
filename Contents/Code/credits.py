# Person credit parsing shared by the update and search paths.


def collect_role_credits(people, scope_type, scope_id, role_name):
    """
        Returns the id-backed credits for one role within an entity scope.

        The deduplication key is (scope_type, scope_id, person.id, role):
        identity is the person ID, never the display name. Payload order is
        preserved. Entries without a person ID or a non-empty name are
        dropped; callers only display names.
    """
    credits = []
    seen = set()
    for relation in people or []:
        person = (relation or {}).get('person') or {}
        role = ((relation or {}).get('role') or {}).get('name')
        person_id = person.get('id')
        name = (person.get('name') or '').strip()
        if role != role_name or not person_id or not name:
            continue
        key = (scope_type, scope_id, person_id, role)
        if key in seen:
            continue
        seen.add(key)
        credits.append({'id': person_id, 'name': name})
    return credits
