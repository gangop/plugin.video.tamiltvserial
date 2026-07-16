# -*- coding: utf-8 -*-

import json
import urllib.error

import xbmc
import xbmcgui
import xbmcplugin

from constants import (
    CHANNEL_GROUPS,
    PROP_AUTOPLAY_ACTIVE,
    PROP_FAILOVER_CANDIDATES,
    PROP_FAILOVER_CATEGORY,
    PROP_FAILOVER_NEXT_POST,
    PROP_FAILOVER_TITLE,
    PROP_NEXT_CATEGORY,
    PROP_NEXT_POST,
    PROP_PLAY_WATCH,
    SHOW_CHANNEL_IDS,
    TAMIL_TV_SHOWS_ID,
)
from favorites import add_favorite, is_favorite, load_favorites, remove_favorite
from scraper import (
    list_posts,
    list_serial_categories,
    list_show_categories_by_latest_episode,
    normalize_post,
    title_matches_serial,
)
from stream_resolver import (
    resolve_episode_stream,
    resolve_fallback_stream,
    verify_stream_reachable,
)
from tamildhool import resolve_from_fallback_index
from utils import (
    addon,
    api_get,
    apply_stream_properties,
    build_plugin_url,
    get_setting_bool,
    get_setting_int,
    inputstream_adaptive_status,
    is_hls_url,
    localize,
    log,
    log_error,
    set_list_label,
    set_video_info,
    strip_html,
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
            'play_failover': self.play_failover,
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

    def _favorite_ids(self):
        return {
            int(item['id'])
            for item in load_favorites()
            if item.get('id') is not None
        }

    def _favorite_context_menu(self, category_id, name, favorite_ids=None):
        category_id = int(category_id)
        is_fav = (
            category_id in favorite_ids
            if favorite_ids is not None
            else is_favorite(category_id)
        )
        if is_fav:
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

    def _add_serial_folder(self, serial, favorite_ids=None):
        category_id = serial['id']
        name = serial['name']
        search_query = serial.get('search_query')
        channel_id = serial.get('channel_id')
        has_category = bool(category_id) and not str(category_id).startswith('search:')
        if has_category:
            is_fav = (
                int(category_id) in favorite_ids
                if favorite_ids is not None
                else is_favorite(category_id)
            )
        else:
            is_fav = False
        label = f'★ {name}' if is_fav else name
        plot = f"Latest: {serial['latest_title']}" if serial.get('latest_title') else f"{serial.get('count', 0)} episodes"
        if search_query:
            params = {
                'action': 'search',
                'query': search_query,
                'title': name,
                'page': 1,
            }
            if channel_id:
                params['channel_id'] = channel_id
            if has_category:
                params['category_id'] = category_id
        else:
            params = {
                'action': 'category',
                'category_id': category_id,
                'title': name,
                'page': 1,
            }
        self._add_folder(
            label,
            params,
            plot=plot,
            context_menu=(
                self._favorite_context_menu(category_id, name, favorite_ids)
                if has_category
                else None
            ),
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

    def _clear_failover(self):
        window = xbmcgui.Window(10000)
        window.clearProperty(PROP_PLAY_WATCH)
        window.clearProperty(PROP_FAILOVER_CANDIDATES)
        window.clearProperty(PROP_FAILOVER_TITLE)
        window.clearProperty(PROP_FAILOVER_NEXT_POST)
        window.clearProperty(PROP_FAILOVER_CATEGORY)

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

    @staticmethod
    def _candidate(source, url, referer='', cookies=''):
        return {
            'source': source,
            'url': url,
            'referer': referer or '',
            'cookies': cookies or '',
        }

    def _resolve_source(self, source, episode):
        """Resolve one source name to a stream triple, without verifying."""
        title = episode.get('title', '')
        if source == 'tamildhool-index':
            return resolve_from_fallback_index(title)
        if source == 'tamiltvserial':
            return resolve_episode_stream(
                episode.get('content_html', ''),
                episode_link=episode.get('link', ''),
                episode_title=title,
                allow_fallback=False,
            )
        if source == 'tamildhool-live':
            return resolve_fallback_stream(title, use_index=False)
        return '', '', ''

    def _next_verified_candidate(self, episode, source_order):
        """
        Walk source_order, verify each, return (candidate, remaining_sources).
        remaining_sources are unverified source names for later failover.
        """
        remaining = list(source_order)
        while remaining:
            source = remaining.pop(0)
            log(f'Resolving {source} for {episode.get("title", "")!r}')
            url, referer, cookies = self._resolve_source(source, episode)
            if not url:
                log(f'{source} unavailable')
                continue
            if not verify_stream_reachable(url, referer, cookies):
                log_error(f'{source} stream unreachable; trying next source')
                continue
            log(f'Accepted {source}')
            return self._candidate(source, url, referer, cookies), remaining
        return None, []

    def _store_failover(self, remaining_sources, episode, next_post_id, category_id):
        """Arm playback-start watch so silent stalls get failover or an error toast."""
        window = xbmcgui.Window(10000)
        if not episode.get('id'):
            self._clear_failover()
            return
        payload = {
            'sources': list(remaining_sources or []),
            'post_id': int(episode['id']),
            'title': episode.get('title', 'Episode'),
            'next_post_id': str(next_post_id or ''),
            'category_id': str(category_id or ''),
        }
        window.setProperty(PROP_FAILOVER_CANDIDATES, json.dumps(payload))
        window.setProperty(PROP_FAILOVER_TITLE, episode.get('title', 'Episode'))
        window.setProperty(PROP_FAILOVER_NEXT_POST, str(next_post_id or ''))
        window.setProperty(PROP_FAILOVER_CATEGORY, str(category_id or ''))
        window.setProperty(PROP_PLAY_WATCH, '1')

    def _play_candidate(self, candidate, episode, next_post_id='', category_id='', remaining_sources=None):
        stream_url = candidate['url']
        stream_referer = candidate.get('referer', '')
        stream_cookies = candidate.get('cookies', '')
        source = candidate.get('source', 'unknown')
        title = episode.get('title', 'Episode')

        # Non-Bunny HLS still needs InputStream Adaptive.
        # BunnyCDN uses a localhost proxy + default player (no ISA required).
        is_bunny = 'b-cdn.net' in (stream_url or '').lower()
        if is_hls_url(stream_url) and not is_bunny:
            isa_status = inputstream_adaptive_status()
            if isa_status == 'disabled':
                self._clear_autoplay()
                self._clear_failover()
                xbmcgui.Dialog().ok(addon().getAddonInfo('name'), localize(30041))
                xbmcplugin.setResolvedUrl(self.handle, False, xbmcgui.ListItem())
                return False
            if isa_status == 'missing':
                # Only block when detection is confident; otherwise try playback.
                log_error('InputStream Adaptive appears missing; showing install help')
                self._clear_autoplay()
                self._clear_failover()
                xbmcgui.Dialog().ok(
                    localize(30038) or 'InputStream Adaptive required',
                    localize(30037),
                )
                xbmcplugin.setResolvedUrl(self.handle, False, xbmcgui.ListItem())
                return False
            if isa_status == 'ready':
                log('InputStream Adaptive ready')

        self._schedule_autoplay(next_post_id, category_id)
        self._store_failover(remaining_sources or [], episode, next_post_id, category_id)

        list_item = xbmcgui.ListItem(label=title or 'Episode')
        apply_stream_properties(list_item, stream_url, stream_referer, cookies=stream_cookies)
        list_item.setProperty('IsPlayable', 'true')
        playback_path = list_item.getPath() if hasattr(list_item, 'getPath') else stream_url
        log(f'Playing via {source}: {playback_path[:120]}')
        xbmcplugin.setResolvedUrl(self.handle, True, list_item)
        return True

    def play_failover(self, _params):
        """Resolve and play the next alternate source after a start timeout."""
        window = xbmcgui.Window(10000)
        raw = window.getProperty(PROP_FAILOVER_CANDIDATES)
        try:
            payload = json.loads(raw) if raw else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}

        sources = list(payload.get('sources') or [])
        post_id = payload.get('post_id')
        next_post_id = payload.get('next_post_id') or window.getProperty(PROP_FAILOVER_NEXT_POST)
        category_id = payload.get('category_id') or window.getProperty(PROP_FAILOVER_CATEGORY)

        if not post_id or not sources:
            self._clear_failover()
            xbmcplugin.setResolvedUrl(self.handle, False, xbmcgui.ListItem())
            return

        posts, _headers = api_get('posts', params={'include': int(post_id)})
        if not posts:
            self._clear_failover()
            xbmcplugin.setResolvedUrl(self.handle, False, xbmcgui.ListItem())
            return

        episode = normalize_post(posts[0])
        candidate, remaining = self._next_verified_candidate(episode, sources)
        if not candidate:
            self._clear_failover()
            xbmcgui.Dialog().notification(
                addon().getAddonInfo('name'),
                localize(30020),
                xbmcgui.NOTIFICATION_ERROR,
                5000,
            )
            xbmcplugin.setResolvedUrl(self.handle, False, xbmcgui.ListItem())
            return

        xbmcgui.Dialog().notification(
            addon().getAddonInfo('name'),
            localize(30049),
            xbmcgui.NOTIFICATION_INFO,
            2500,
        )
        self._play_candidate(
            candidate,
            episode=episode,
            next_post_id=next_post_id,
            category_id=category_id,
            remaining_sources=remaining,
        )

    def play(self, params):
        try:
            self._play(params)
        except Exception as exc:
            log_error(f'Play failed: {exc}')
            self._clear_autoplay()
            self._clear_failover()
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
        posts, _headers = api_get('posts', params={'include': post_id})
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

        # Universal order for every episode: TamilDhool index → TamilTvSerial → TamilDhool live.
        source_order = ['tamildhool-index', 'tamiltvserial', 'tamildhool-live']
        candidate, remaining = self._next_verified_candidate(episode, source_order)
        if not candidate:
            self._clear_autoplay()
            self._clear_failover()
            log_error(f'No stream resolved for post_id={post_id}')
            xbmcgui.Dialog().notification(
                addon().getAddonInfo('name'),
                localize(30020),
                xbmcgui.NOTIFICATION_ERROR,
                5000,
            )
            xbmcplugin.setResolvedUrl(self.handle, False, xbmcgui.ListItem())
            return

        self._play_candidate(
            candidate,
            episode=episode,
            next_post_id=params.get('next_post_id', ''),
            category_id=category_id,
            remaining_sources=remaining,
        )

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

        favorite_ids = {
            int(item['id'])
            for item in favorites
            if item.get('id') is not None
        }
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
                context_menu=self._favorite_context_menu(category_id, name, favorite_ids),
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

        favorite_ids = self._favorite_ids()
        for serial in list_serial_categories(category_id):
            self._add_serial_folder(serial, favorite_ids)

        xbmcplugin.endOfDirectory(self.handle)

    def show_show_groups(self, params):
        title = params.get('title', localize(30016))
        category_id = int(params.get('category_id', TAMIL_TV_SHOWS_ID))
        only_unclassified = str(params.get('other_shows', '')).lower() in ('1', 'true', 'yes')
        xbmcplugin.setPluginCategory(self.handle, title)
        self._set_view('files')

        favorite_ids = self._favorite_ids()
        for subcategory in list_show_categories_by_latest_episode(
            category_id,
            excluded_category_ids=[TAMIL_TV_SHOWS_ID],
            show_channel_ids=SHOW_CHANNEL_IDS,
            only_unclassified=only_unclassified,
        ):
            self._add_serial_folder(subcategory, favorite_ids)

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
        channel_id = params.get('channel_id', '').strip()
        match_title = params.get('title', '').strip() or query

        if not query:
            keyboard = xbmc.Keyboard('', localize(30018))
            keyboard.doModal()
            if not keyboard.isConfirmed():
                xbmcplugin.endOfDirectory(self.handle, succeeded=False)
                return

            query = keyboard.getText().strip()
            match_title = query
        if not query:
            xbmcplugin.endOfDirectory(self.handle, succeeded=False)
            return

        label = params.get('title') or f"{localize(30012)}: {query}"
        xbmcplugin.setPluginCategory(self.handle, label)
        self._set_view('episodes')

        category_id = int(channel_id) if channel_id else None
        posts, page, total_pages = list_posts(
            category_id=category_id,
            search=query,
            page=page,
        )
        if channel_id and match_title:
            posts = [
                post for post in posts
                if title_matches_serial(
                    strip_html((post.get('title') or {}).get('rendered', '')),
                    match_title,
                )
            ]

        base_params = {'action': 'search', 'query': query, 'page': page}
        if channel_id:
            base_params['channel_id'] = channel_id
        if params.get('title'):
            base_params['title'] = params.get('title')
        if params.get('category_id'):
            base_params['category_id'] = params.get('category_id')

        self._finish_listing(
            posts,
            page,
            total_pages,
            base_params,
            category_id=params.get('category_id') or channel_id,
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
