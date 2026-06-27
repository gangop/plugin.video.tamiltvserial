# -*- coding: utf-8 -*-

import urllib.error

import xbmc
import xbmcgui
import xbmcplugin

from constants import CHANNELS, PROP_AUTOPLAY_ACTIVE, PROP_NEXT_CATEGORY, PROP_NEXT_POST, TAMIL_TV_SHOWS_ID
from favorites import add_favorite, is_favorite, load_favorites, remove_favorite
from scraper import find_next_post_id, list_child_categories, list_posts, next_post_id_from_list, normalize_post
from stream_resolver import resolve_episode_stream
from utils import (
    addon,
    api_get,
    apply_stream_properties,
    build_plugin_url,
    get_setting_bool,
    inputstream_adaptive_status,
    is_hls_url,
    localize,
    log_error,
    set_list_label,
    set_video_info,
)


class Router:
    def __init__(self, plugin_url, handle):
        self.plugin_url = plugin_url
        self.handle = handle

    def run(self, params):
        action = params.get('action', 'root')

        routes = {
            'root': self.show_root,
            'latest': self.show_latest,
            'favorites': self.show_favorites,
            'browse_channel': self.show_channel_picker,
            'browse_serials': self.show_serials,
            'browse_shows': self.show_show_groups,
            'category': self.show_category,
            'search': self.search,
            'diagnostics': self.show_diagnostics,
            'add_favorite': self.add_favorite_action,
            'remove_favorite': self.remove_favorite_action,
            'play': self.play,
        }

        handler = routes.get(action, self.show_root)
        try:
            handler(params)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            log_error(f'Network error in {action}: {exc}')
            self._fail(localize(30039), is_play=(action == 'play'))
        except Exception as exc:
            log_error(f'Unhandled error in {action}: {exc}')
            self._fail(localize(30040), is_play=(action == 'play'))

    def _fail(self, message, is_play=False):
        xbmcgui.Dialog().ok(addon().getAddonInfo('name'), message)
        if is_play:
            xbmcplugin.setResolvedUrl(self.handle, False, xbmcgui.ListItem())
        else:
            xbmcplugin.endOfDirectory(self.handle, succeeded=False)

    def _set_view(self, content_type='episodes'):
        xbmcplugin.setContent(self.handle, content_type)

    def _favorite_context_menu(self, category_id, name):
        if is_favorite(category_id):
            url = build_plugin_url(
                self.plugin_url,
                action='remove_favorite',
                category_id=category_id,
                title=name,
            )
            label = localize(30032)
        else:
            url = build_plugin_url(
                self.plugin_url,
                action='add_favorite',
                category_id=category_id,
                title=name,
            )
            label = localize(30031)
        return [(label, f'RunPlugin({url})')]

    def _add_folder(self, label, params, plot='', context_menu=None):
        list_item = xbmcgui.ListItem(label=label)
        set_list_label(list_item, label)
        info_dict = {'title': label}
        if plot:
            info_dict['plot'] = plot
        set_video_info(list_item, info_dict)
        if context_menu:
            list_item.addContextMenuItems(context_menu)

        url = build_plugin_url(self.plugin_url, **params)
        xbmcplugin.addDirectoryItem(self.handle, url, list_item, True)

    def _add_info_item(self, label):
        list_item = xbmcgui.ListItem(label=label)
        set_list_label(list_item, label)
        xbmcplugin.addDirectoryItem(self.handle, self.plugin_url, list_item, False)

    def _add_serial_folder(self, serial):
        category_id = serial['id']
        name = serial['name']
        label = f'★ {name}' if is_favorite(category_id) else name
        self._add_folder(
            label,
            {
                'action': 'category',
                'category_id': category_id,
                'title': name,
                'page': 1,
            },
            plot=f"{serial.get('count', 0)} episodes",
            context_menu=self._favorite_context_menu(category_id, name),
        )

    def _add_episode(self, episode, category_id=None, next_post_id=None):
        list_item = xbmcgui.ListItem(label=episode['title'])
        set_list_label(list_item, episode['title'])
        if episode.get('thumb'):
            list_item.setArt({
                'thumb': episode['thumb'],
                'icon': episode['thumb'],
                'poster': episode['thumb'],
            })

        info_dict = {
            'title': episode['title'],
            'plot': episode.get('plot', ''),
            'mediatype': 'episode',
        }
        if episode.get('categories'):
            info_dict['tvshowtitle'] = episode['categories'][0]
        if episode.get('episode_number') is not None:
            info_dict['episode'] = episode['episode_number']
        set_video_info(list_item, info_dict)

        list_item.setProperty('IsPlayable', 'true')
        play_params = {'action': 'play', 'post_id': episode['id']}
        if category_id:
            play_params['category_id'] = category_id
        if next_post_id:
            play_params['next_post_id'] = next_post_id
        url = build_plugin_url(self.plugin_url, **play_params)
        xbmcplugin.addDirectoryItem(self.handle, url, list_item, False)

    def _finish_listing(self, posts, page, total_pages, base_params, category_id=None):
        if not posts:
            xbmcgui.Dialog().ok(addon().getAddonInfo('name'), localize(30019))

        for index, post in enumerate(posts):
            episode = normalize_post(post)
            next_post_id = ''
            if category_id:
                next_post_id = next_post_id_from_list(posts, index)
            self._add_episode(episode, category_id=category_id, next_post_id=next_post_id)

        if page < total_pages:
            next_params = dict(base_params)
            next_params['page'] = page + 1
            self._add_folder(localize(30017), next_params)

        xbmcplugin.addSortMethod(self.handle, xbmcplugin.SORT_METHOD_DATE)
        xbmcplugin.addSortMethod(self.handle, xbmcplugin.SORT_METHOD_LABEL)
        xbmcplugin.endOfDirectory(self.handle)

    def _clear_autoplay(self):
        window = xbmcgui.Window(10000)
        window.clearProperty(PROP_NEXT_POST)
        window.clearProperty(PROP_NEXT_CATEGORY)
        window.clearProperty(PROP_AUTOPLAY_ACTIVE)

    def _schedule_autoplay(self, next_post_id, category_id):
        if not get_setting_bool('autoplay_next', True):
            self._clear_autoplay()
            return

        if not next_post_id:
            self._clear_autoplay()
            return

        window = xbmcgui.Window(10000)
        window.setProperty(PROP_NEXT_POST, str(next_post_id))
        window.setProperty(PROP_NEXT_CATEGORY, str(category_id or ''))
        window.setProperty(PROP_AUTOPLAY_ACTIVE, '1')

    def show_root(self, _params):
        version = addon().getAddonInfo('version')
        xbmcplugin.setPluginCategory(self.handle, f"{addon().getAddonInfo('name')} v{version}")
        self._set_view('files')

        self._add_folder(localize(30010), {'action': 'latest', 'page': 1})
        self._add_folder(localize(30022), {'action': 'favorites'})
        self._add_folder(localize(30011), {'action': 'browse_channel'})
        if get_setting_bool('enable_search', True):
            self._add_folder(localize(30012), {'action': 'search'})
        self._add_folder(localize(30042), {'action': 'diagnostics'})

        xbmcplugin.endOfDirectory(self.handle)

    def show_diagnostics(self, _params):
        title = localize(30042)
        xbmcplugin.setPluginCategory(self.handle, title)
        self._set_view('files')

        lines = [
            localize(30043),
            f'Addon version: {addon().getAddonInfo("version")}',
            'Menu opened successfully',
            'Next step: try Latest Episodes',
        ]

        for line in lines:
            self._add_folder(line, {'action': 'root'})

        xbmcplugin.endOfDirectory(self.handle, succeeded=True)

    def show_favorites(self, _params):
        xbmcplugin.setPluginCategory(self.handle, localize(30022))
        self._set_view('files')

        favorites = load_favorites()
        if not favorites:
            xbmcgui.Dialog().ok(addon().getAddonInfo('name'), localize(30034))

        for item in favorites:
            category_id = item['id']
            name = item.get('name', 'Serial')
            self._add_folder(
                name,
                {
                    'action': 'category',
                    'category_id': category_id,
                    'title': name,
                    'page': 1,
                },
                context_menu=self._favorite_context_menu(category_id, name),
            )

        xbmcplugin.endOfDirectory(self.handle)

    def show_latest(self, params):
        page = int(params.get('page', 1))
        xbmcplugin.setPluginCategory(self.handle, localize(30010))
        self._set_view('episodes')

        posts, page, total_pages = list_posts(page=page)
        self._finish_listing(posts, page, total_pages, {'action': 'latest', 'page': page})

    def show_channel_picker(self, _params):
        xbmcplugin.setPluginCategory(self.handle, localize(30011))
        self._set_view('files')

        for channel in CHANNELS:
            if channel['mode'] == 'shows':
                params = {
                    'action': 'browse_shows',
                    'title': channel['name'],
                }
            else:
                params = {
                    'action': 'browse_serials',
                    'category_id': channel['id'],
                    'title': channel['name'],
                }
            label = localize(channel['label_id']) or channel['name']
            self._add_folder(label, params)

        xbmcplugin.endOfDirectory(self.handle)

    def show_serials(self, params):
        category_id = int(params['category_id'])
        title = params.get('title', '')
        xbmcplugin.setPluginCategory(self.handle, title)
        self._set_view('files')

        for serial in list_child_categories(category_id):
            self._add_serial_folder(serial)

        xbmcplugin.endOfDirectory(self.handle)

    def show_show_groups(self, params):
        title = params.get('title', localize(30016))
        xbmcplugin.setPluginCategory(self.handle, title)
        self._set_view('files')

        for subcategory in list_child_categories(TAMIL_TV_SHOWS_ID):
            self._add_serial_folder(subcategory)

        xbmcplugin.endOfDirectory(self.handle)

    def show_category(self, params):
        category_id = int(params['category_id'])
        title = params.get('title', '')
        page = int(params.get('page', 1))

        xbmcplugin.setPluginCategory(self.handle, title)
        self._set_view('episodes')

        posts, page, total_pages = list_posts(category_id=category_id, page=page)
        self._finish_listing(
            posts,
            page,
            total_pages,
            {
                'action': 'category',
                'category_id': category_id,
                'title': title,
                'page': page,
            },
            category_id=category_id,
        )

    def search(self, params):
        query = params.get('query', '').strip()
        page = int(params.get('page', 1))

        if not query:
            keyboard = xbmc.Keyboard('', localize(30018))
            keyboard.doModal()
            if not keyboard.isConfirmed():
                xbmcplugin.endOfDirectory(self.handle, succeeded=False)
                return

            query = keyboard.getText().strip()
        if not query:
            xbmcplugin.endOfDirectory(self.handle, succeeded=False)
            return

        xbmcplugin.setPluginCategory(self.handle, f"{localize(30012)}: {query}")
        self._set_view('episodes')

        posts, page, total_pages = list_posts(search=query, page=page)
        self._finish_listing(
            posts,
            page,
            total_pages,
            {'action': 'search', 'query': query, 'page': page},
        )

    def add_favorite_action(self, params):
        category_id = int(params['category_id'])
        name = params.get('title', 'Serial')
        if add_favorite(category_id, name):
            xbmcgui.Dialog().notification(
                addon().getAddonInfo('name'),
                localize(30033),
                xbmcgui.NOTIFICATION_INFO,
                3000,
            )
        xbmc.executebuiltin('Container.Refresh')

    def remove_favorite_action(self, params):
        category_id = int(params['category_id'])
        if remove_favorite(category_id):
            xbmcgui.Dialog().notification(
                addon().getAddonInfo('name'),
                localize(30035),
                xbmcgui.NOTIFICATION_INFO,
                3000,
            )
        xbmc.executebuiltin('Container.Refresh')

    def play(self, params):
        try:
            self._play(params)
        except Exception as exc:
            log_error(f'Play failed: {exc}')
            self._clear_autoplay()
            xbmcgui.Dialog().notification(
                addon().getAddonInfo('name'),
                localize(30040),
                xbmcgui.NOTIFICATION_ERROR,
                5000,
            )
            xbmcplugin.setResolvedUrl(self.handle, False, xbmcgui.ListItem())

    def _play(self, params):
        post_id = params.get('post_id')
        if not post_id:
            xbmcplugin.setResolvedUrl(self.handle, False, xbmcgui.ListItem())
            return

        post_id = int(post_id)
        category_id = params.get('category_id', '')
        posts, _headers = api_get('posts', params={'include': post_id, '_embed': 1})
        if not posts:
            xbmcgui.Dialog().notification(
                addon().getAddonInfo('name'),
                localize(30020),
                xbmcgui.NOTIFICATION_ERROR,
                5000,
            )
            xbmcplugin.setResolvedUrl(self.handle, False, xbmcgui.ListItem())
            return

        episode = normalize_post(posts[0])
        xbmcgui.Dialog().notification(
            addon().getAddonInfo('name'),
            localize(30021),
            xbmcgui.NOTIFICATION_INFO,
            2000,
        )

        stream_url, stream_referer = resolve_episode_stream(
            episode.get('content_html', ''),
            episode_link=episode.get('link', ''),
        )
        if not stream_url:
            self._clear_autoplay()
            log_error(f'No stream resolved for post_id={post_id}')
            xbmcgui.Dialog().notification(
                addon().getAddonInfo('name'),
                localize(30020),
                xbmcgui.NOTIFICATION_ERROR,
                5000,
            )
            xbmcplugin.setResolvedUrl(self.handle, False, xbmcgui.ListItem())
            return

        if is_hls_url(stream_url):
            isa_status = inputstream_adaptive_status()
            if isa_status != 'ready':
                self._clear_autoplay()
                message = localize(30041) if isa_status == 'disabled' else localize(30037)
                xbmcgui.Dialog().ok(addon().getAddonInfo('name'), message)
                xbmcplugin.setResolvedUrl(self.handle, False, xbmcgui.ListItem())
                return

        self._schedule_autoplay(params.get('next_post_id', ''), category_id)

        list_item = xbmcgui.ListItem(label=episode.get('title', 'Episode'))
        apply_stream_properties(list_item, stream_url, stream_referer)
        list_item.setProperty('IsPlayable', 'true')
        playback_path = list_item.getPath() if hasattr(list_item, 'getPath') else stream_url
        log_error(f'Playing via {playback_path[:120]}')
        xbmcplugin.setResolvedUrl(self.handle, True, list_item)
