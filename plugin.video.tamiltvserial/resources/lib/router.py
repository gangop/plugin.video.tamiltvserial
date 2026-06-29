# -*- coding: utf-8 -*-

import urllib.error

import xbmc
import xbmcgui
import xbmcplugin

from constants import CHANNEL_GROUPS, PROP_AUTOPLAY_ACTIVE, PROP_NEXT_CATEGORY, PROP_NEXT_POST, SHOW_CHANNEL_IDS, TAMIL_TV_SHOWS_ID
from favorites import add_favorite, is_favorite, load_favorites, remove_favorite
from scraper import find_next_post_id, list_child_categories, list_posts, list_show_categories_by_latest_episode, normalize_post
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
            'browse_channel_group': self.show_channel_group,
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
        search_query = serial.get('search_query')
        has_category = not search_query
        label = f'★ {name}' if has_category and is_favorite(category_id) else name
        plot = f"Latest: {serial['latest_title']}" if serial.get('latest_title') else f"{serial.get('count', 0)} episodes"
        params = {
            'action': 'search',
            'query': search_query,
            'page': 1,
        } if search_query else {
            'action': 'category',
            'category_id': category_id,
            'title': name,
            'page': 1,
        }
        self._add_folder(
            label,
            params,
            plot=plot,
            context_menu=self._favorite_context_menu(category_id, name) if has_category else None,
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

    @staticmethod
    def _episode_desc_key(episode):
        return (
            episode.get('date') or '',
            episode.get('episode_number') or 0,
            episode.get('id') or 0,
        )

    def _finish_listing(
        self,
        posts,
        page,
        total_pages,
        base_params,
        category_id=None,
        force_desc=False,
        add_sort_methods=True,
    ):
        if not posts:
            xbmcgui.Dialog().ok(addon().getAddonInfo('name'), localize(30019))

        episodes = [normalize_post(post) for post in posts]
        if force_desc:
            episodes.sort(key=self._episode_desc_key, reverse=True)

        for index, episode in enumerate(episodes):
            next_post_id = ''
            if category_id:
                if index > 0:
                    next_post_id = str(episodes[index - 1].get('id', ''))
            self._add_episode(episode, category_id=category_id, next_post_id=next_post_id)

        if page < total_pages:
            next_params = dict(base_params)
            next_params['page'] = page + 1
            self._add_folder(localize(30017), next_params)

        if add_sort_methods:
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

        for channel in CHANNEL_GROUPS:
            self._add_folder(
                channel['name'],
                {
                    'action': 'browse_channel_group',
                    'title': channel['name'],
                    'serials_id': channel.get('serials_id'),
                    'shows_id': channel.get('shows_id'),
                    'other_shows': 1 if channel.get('other_shows') else 0,
                },
            )

        xbmcplugin.endOfDirectory(self.handle)

    def show_channel_group(self, params):
        title = params.get('title', '')
        xbmcplugin.setPluginCategory(self.handle, title)
        self._set_view('files')

        serials_id = params.get('serials_id')
        shows_id = params.get('shows_id')
        if serials_id:
            self._add_folder(
                localize(30045) or 'Serials',
                {
                    'action': 'browse_serials',
                    'category_id': serials_id,
                    'title': f'{title} {localize(30045) or "Serials"}',
                },
            )
        if shows_id:
            self._add_folder(
                localize(30046) or 'Shows',
                {
                    'action': 'browse_shows',
                    'category_id': shows_id,
                    'title': f'{title} {localize(30046) or "Shows"}',
                    'other_shows': params.get('other_shows', 0),
                },
            )

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
        category_id = int(params.get('category_id', TAMIL_TV_SHOWS_ID))
        only_unclassified = str(params.get('other_shows', '')).lower() in ('1', 'true', 'yes')
        xbmcplugin.setPluginCategory(self.handle, title)
        self._set_view('files')

        for subcategory in list_show_categories_by_latest_episode(
            category_id,
            excluded_category_ids=[TAMIL_TV_SHOWS_ID],
            show_channel_ids=SHOW_CHANNEL_IDS,
            only_unclassified=only_unclassified,
        ):
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
            force_desc=True,
            add_sort_methods=False,
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
            force_desc=True,
            add_sort_methods=False,
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
            if isa_status == 'disabled':
                self._clear_autoplay()
                xbmcgui.Dialog().ok(addon().getAddonInfo('name'), localize(30041))
                xbmcplugin.setResolvedUrl(self.handle, False, xbmcgui.ListItem())
                return
            if isa_status == 'missing':
                log_error('InputStream Adaptive status reported missing; trying playback anyway')

        self._schedule_autoplay(params.get('next_post_id', ''), category_id)

        list_item = xbmcgui.ListItem(label=episode.get('title', 'Episode'))
        apply_stream_properties(list_item, stream_url, stream_referer)
        list_item.setProperty('IsPlayable', 'true')
        playback_path = list_item.getPath() if hasattr(list_item, 'getPath') else stream_url
        log_error(f'Playing via {playback_path[:120]}')
        xbmcplugin.setResolvedUrl(self.handle, True, list_item)
