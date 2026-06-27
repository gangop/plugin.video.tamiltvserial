# -*- coding: utf-8 -*-

import json
import os

from utils import addon, log, log_error


FAVORITES_FILE = 'favorites.json'


def _favorites_path():
    return os.path.join(addon().getAddonInfo('profile'), FAVORITES_FILE)


def load_favorites():
    path = _favorites_path()
    if not os.path.exists(path):
        return []

    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
        if isinstance(data, list):
            return data
    except (OSError, json.JSONDecodeError) as exc:
        log_error(f'Failed to load favorites: {exc}')
    return []


def save_favorites(items):
    path = _favorites_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(items, handle, indent=2)
    log(f'Saved {len(items)} favorites')


def is_favorite(category_id):
    category_id = int(category_id)
    return any(item.get('id') == category_id for item in load_favorites())


def add_favorite(category_id, name):
    category_id = int(category_id)
    items = load_favorites()
    if any(item.get('id') == category_id for item in items):
        return False
    items.append({'id': category_id, 'name': name})
    save_favorites(items)
    return True


def remove_favorite(category_id):
    category_id = int(category_id)
    items = load_favorites()
    updated = [item for item in items if item.get('id') != category_id]
    if len(updated) == len(items):
        return False
    save_favorites(updated)
    return True
