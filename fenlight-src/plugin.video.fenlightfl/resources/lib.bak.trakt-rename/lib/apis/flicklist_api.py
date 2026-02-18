"""
FlickList API Client — Drop-in replacement for fl_api.py

All function signatures match fl_api.py for seamless import swap.
Internally calls FlickList API instead of Trakt.

FlickList API returns MediaCard: {id, tmdb_id, media_type, title, year, poster_path, ...}
Paginated: {results: [...], page, total_pages, total_results}
This module transforms responses to Trakt-compatible shapes for the rest of the addon.
"""
import json
import time
import requests
from urllib.parse import unquote, quote_plus
from caches import flicklist_cache
from caches.settings_cache import get_setting, set_setting
from caches.main_cache import cache_object
from caches.lists_cache import lists_cache_object
from modules import kodi_utils, settings
from modules.metadata import movie_meta_external_id, tvshow_meta_external_id
from modules.utils import sort_list, sort_for_article, get_datetime, timedelta, replace_html_codes, copy2clip, make_qrcode, make_tinyurl, \
							make_thread_list, jsondate_to_datetime as js2date

API_BASE = 'https://beta.flicklist.tv/api'
FLICKLIST_CLIENT_ID = 'flicklist_kodi_addon'


def _to_fl_movie(item):
	"""Transform a FlickList MediaCard to Trakt movie dict."""
	return {
		'movie': {
			'title': item.get('title', ''),
			'year': item.get('year'),
			'ids': {
				'tmdb': item.get('tmdb_id') or item.get('id'),
				'imdb': item.get('imdb_id', ''),
				'tvdb': 0,
				'slug': item.get('slug', '')
			}
		}
	}

def _to_fl_show(item):
	"""Transform a FlickList MediaCard to Trakt show dict."""
	return {
		'show': {
			'title': item.get('title', ''),
			'year': item.get('year'),
			'ids': {
				'tmdb': item.get('tmdb_id') or item.get('id'),
				'imdb': item.get('imdb_id', ''),
				'tvdb': item.get('tvdb_id', 0),
				'slug': item.get('slug', '')
			}
		}
	}

def _to_fl_media(item):
	"""Auto-detect movie or show and transform."""
	mtype = item.get('media_type', 'movie')
	if mtype == 'tv':
		return _to_fl_show(item)
	return _to_fl_movie(item)

def _extract_paginated(data):
	"""Extract items and page count from FlickList Paginated response."""
	if data is None:
		return [], '1'
	if isinstance(data, dict):
		items = data.get('results', data.get('items', []))
		page_count = str(data.get('total_pages', 1))
		return items, page_count
	if isinstance(data, list):
		return data, '1'
	return [], '1'

def _media_to_fl_list(data, media_type='movie'):
	"""Transform a paginated FlickList response to a list of Trakt-compatible dicts."""
	items, page_count = _extract_paginated(data)
	if media_type in ('tv', 'show', 'shows'):
		return [_to_fl_show(i) for i in items], page_count
	elif media_type == 'mixed':
		return [_to_fl_media(i) for i in items], page_count
	return [_to_fl_movie(i) for i in items], page_count


def call_flicklist(path, params=None, data=None, is_delete=False, with_auth=True, method=None, pagination=False, page_no=1):
	"""Make an HTTP request to the FlickList API."""
	if params is None:
		params = {}
	url = '%s%s' % (API_BASE, path)
	headers = {'Content-Type': 'application/json'}
	if with_auth:
		token = get_setting('fenlightfl.flicklist.token')
		if token and token not in ('0', 'empty_setting', ''):
			headers['Authorization'] = 'Bearer %s' % token
	if pagination:
		params['page'] = page_no
		if 'per_page' not in params:
			params['per_page'] = 20
	try:
		if method:
			if method == 'post':
				resp = requests.post(url, headers=headers, timeout=15)
			elif method == 'delete':
				resp = requests.delete(url, headers=headers, timeout=15)
			else:
				resp = requests.get(url, params=params, headers=headers, timeout=15)
		elif data is not None:
			resp = requests.post(url, json=data, headers=headers, timeout=15)
		elif is_delete:
			resp = requests.delete(url, headers=headers, timeout=15)
		else:
			resp = requests.get(url, params=params, headers=headers, timeout=15)
		resp.raise_for_status()
	except Exception as e:
		kodi_utils.logger('FlickList Error', str(e))
		if pagination:
			return (None, page_no)
		return None
	if resp.status_code == 401:
		kodi_utils.logger('FlickList', 'Unauthorized — token may be expired')
		if pagination:
			return (None, page_no)
		return None
	if resp.status_code == 429:
		retry_after = int(resp.headers.get('Retry-After', 5))
		kodi_utils.sleep(retry_after * 1000)
		return call_flicklist(path, params=params, data=data, is_delete=is_delete,
							with_auth=with_auth, method=method, pagination=pagination, page_no=page_no)
	try:
		result = resp.json()
	except:
		result = resp.text
	if pagination:
		if isinstance(result, dict):
			page_count = result.get('total_pages', page_no)
		else:
			page_count = page_no
		return (result, page_count)
	return result

def get_trakt(params):
	"""Generic FlickList API call with Trakt-compatible interface.
	Called by lists_cache_object and cache_fl_object as the fetch function."""
	path = params.get('fl_path', params.get('path', ''))
	fl_params = params.get('params', {})
	result = call_flicklist(path, params=fl_params, data=params.get('data'),
							is_delete=params.get('is_delete', False),
							with_auth=params.get('with_auth', False),
							method=params.get('method'),
							pagination=params.get('pagination', True),
							page_no=params.get('page_no'))
	if params.get('pagination', True):
		if isinstance(result, tuple):
			return result[0]
		return result
	return result


def fl_get_device_code():
	"""Request a device authorization code from FlickList."""
	data = {'client_id': FLICKLIST_CLIENT_ID}
	return call_flicklist('/auth/device/code', data=data, with_auth=False)

def fl_get_device_token(device_codes):
	"""Poll for device token after user authorizes."""
	result = None
	try:
		start = time.time()
		expires_in = device_codes.get('expires_in', 900)
		sleep_interval = device_codes.get('interval', 5)
		user_code = str(device_codes.get('user_code', ''))
		verification_uri = device_codes.get('verification_uri', 'https://beta.flicklist.tv/link')
		auth_url = '%s?code=%s' % (verification_uri, user_code)
		qr_code = make_qrcode(auth_url) or ''
		short_url = make_tinyurl(auth_url)
		copy2clip(auth_url)
		if short_url:
			p_dialog_insert = '[CR]OR....[CR]visit [B]%s[/B]' % short_url
		else:
			p_dialog_insert = ''
		content = 'Enter [B]%s[/B] at [B]%s[/B][CR]OR....[CR]Scan the [B]QR Code[/B]%s' % (user_code, verification_uri, p_dialog_insert)
		progressDialog = kodi_utils.progress_dialog('FlickList Authorize', qr_code)
		progressDialog.update(content, 0)
		try:
			time_passed = 0
			while not progressDialog.iscanceled() and time_passed < expires_in:
				kodi_utils.sleep(max(sleep_interval, 1) * 1000)
				response = call_flicklist('/auth/device/token',
										data={'device_code': device_codes.get('device_code', '')},
										with_auth=False)
				if response and isinstance(response, dict):
					if response.get('access_token'):
						result = response
						break
					error = response.get('error', '')
					if error == 'authorization_pending':
						time_passed = time.time() - start
						progress = int(100 * time_passed / expires_in)
						progressDialog.update(content, progress)
					elif error in ('expired_token', 'access_denied'):
						break
				else:
					time_passed = time.time() - start
					progress = int(100 * time_passed / expires_in)
					progressDialog.update(content, progress)
		except:
			pass
		try:
			progressDialog.close()
		except:
			pass
	except:
		pass
	return result

def fl_refresh_token():
	"""FlickList tokens are long-lived. Check validity and re-auth if needed."""
	try:
		token = get_setting('fenlightfl.flicklist.token')
		if not token or token in ('0', 'empty_setting', ''):
			return
		response = call_flicklist('/auth/me', with_auth=True)
		if response is None:
			kodi_utils.logger('FlickList', 'Token validation failed — may need re-auth')
	except:
		pass

def fl_authenticate(dummy=''):
	"""Run the full FlickList device authorization flow."""
	code = fl_get_device_code()
	if not code:
		kodi_utils.notification('FlickList Error — Could not get device code', 3000)
		return False
	token = fl_get_device_token(code)
	if token:
		set_setting('flicklist.token', token.get('access_token', ''))
		set_setting('watched_indicators', '1')
		kodi_utils.sleep(1000)
		try:
			user = call_flicklist('/auth/me', with_auth=True)
			if user:
				set_setting('flicklist.user', str(user.get('username', user.get('display_name', ''))))
		except:
			pass
		kodi_utils.notification('FlickList Account Authorized', 3000)
		fl_sync_activities(force_update=True)
		return True
	kodi_utils.notification('FlickList Error Authorizing', 3000)
	return False

def fl_revoke_authentication(dummy=''):
	"""Clear FlickList authorization."""
	set_setting('flicklist.user', 'empty_setting')
	set_setting('flicklist.token', '0')
	set_setting('flicklist.next_daily_clear', '0')
	set_setting('watched_indicators', '0')
	flicklist_cache.clear_all_fl_cache_data(silent=True, refresh=False)
	kodi_utils.notification('FlickList Account Authorization Reset', 3000)


def fl_movies_related(imdb_id):
	def _process(params):
		data = call_flicklist('/movies/%s/similar' % imdb_id, with_auth=False)
		items, _ = _media_to_fl_list(data, 'movie')
		return items[:20]
	string = 'fl_movies_related_%s' % imdb_id
	return lists_cache_object(_process, string, {})

def fl_movies_trending(page_no):
	def _process(params):
		data = call_flicklist('/movies/trending', params={'page': page_no, 'per_page': 20}, with_auth=False)
		items, _ = _media_to_fl_list(data, 'movie')
		return items
	string = 'fl_movies_trending_%s' % page_no
	return lists_cache_object(_process, string, {})

def fl_movies_trending_recent(page_no):
	current_year = get_datetime().year
	def _process(params):
		data = call_flicklist('/movies/trending', params={'page': page_no, 'per_page': 20, 'year_min': current_year - 1, 'year_max': current_year}, with_auth=False)
		items, _ = _media_to_fl_list(data, 'movie')
		return items
	string = 'fl_movies_trending_recent_%s' % page_no
	return lists_cache_object(_process, string, {})

def fl_movies_top10_boxoffice(page_no):
	def _process(params):
		data = call_flicklist('/movies/now-playing', params={'per_page': 10}, with_auth=False)
		items, _ = _media_to_fl_list(data, 'movie')
		return items[:10]
	string = 'fl_movies_top10_boxoffice'
	return lists_cache_object(_process, string, {})

def fl_movies_most_watched(page_no):
	def _process(params):
		data = call_flicklist('/movies/trending', params={'page': page_no, 'per_page': 20, 'sort': 'popularity'}, with_auth=False)
		items, _ = _media_to_fl_list(data, 'movie')
		return items
	string = 'fl_movies_most_watched_%s' % page_no
	return lists_cache_object(_process, string, {})

def fl_movies_most_favorited(page_no):
	def _process(params):
		data = call_flicklist('/movies/top-rated', params={'page': page_no, 'per_page': 20}, with_auth=False)
		items, _ = _media_to_fl_list(data, 'movie')
		return items
	string = 'fl_movies_most_favorited%s' % page_no
	return lists_cache_object(_process, string, {})


def fl_tv_related(imdb_id):
	def _process(params):
		data = call_flicklist('/shows/%s/similar' % imdb_id, with_auth=False)
		items, _ = _media_to_fl_list(data, 'tv')
		return items[:20]
	string = 'fl_tv_related_%s' % imdb_id
	return lists_cache_object(_process, string, {})

def fl_tv_trending(page_no):
	def _process(params):
		data = call_flicklist('/shows/trending', params={'page': page_no, 'per_page': 20}, with_auth=False)
		items, _ = _media_to_fl_list(data, 'tv')
		return items
	string = 'fl_tv_trending_%s' % page_no
	return lists_cache_object(_process, string, {})

def fl_tv_trending_recent(page_no):
	current_year = get_datetime().year
	def _process(params):
		data = call_flicklist('/shows/trending', params={'page': page_no, 'per_page': 20, 'year_min': current_year - 1, 'year_max': current_year}, with_auth=False)
		items, _ = _media_to_fl_list(data, 'tv')
		return items
	string = 'fl_tv_trending_recent_%s' % page_no
	return lists_cache_object(_process, string, {})

def fl_tv_most_watched(page_no):
	def _process(params):
		data = call_flicklist('/shows/trending', params={'page': page_no, 'per_page': 20, 'sort': 'popularity'}, with_auth=False)
		items, _ = _media_to_fl_list(data, 'tv')
		return items
	string = 'fl_tv_most_watched_%s' % page_no
	return lists_cache_object(_process, string, {})

def fl_tv_most_favorited(page_no):
	def _process(params):
		data = call_flicklist('/shows/top-rated', params={'page': page_no, 'per_page': 20}, with_auth=False)
		items, _ = _media_to_fl_list(data, 'tv')
		return items
	string = 'fl_tv_most_favorited_%s' % page_no
	return lists_cache_object(_process, string, {})

def fl_tv_certifications(certification, page_no):
	def _process(params):
		data = call_flicklist('/discover', params={'type': 'tv', 'certification': certification, 'page': page_no, 'per_page': 20}, with_auth=False)
		items, _ = _media_to_fl_list(data, 'tv')
		return items
	string = 'fl_tv_certifications_%s_%s' % (certification, page_no)
	return lists_cache_object(_process, string, {})

def fl_tv_search(query, page_no):
	def _process(dummy_arg):
		data = call_flicklist('/search', params={'q': query, 'type': 'tv', 'page': page_no, 'per_page': 20}, with_auth=False,
							pagination=True, page_no=page_no)
		if isinstance(data, tuple):
			raw, page_count = data
		else:
			raw, page_count = data, 1
		items, _ = _extract_paginated(raw)
		fl_items = [_to_fl_show(i) for i in items]
		return (fl_items, str(page_count))
	string = 'fl_tv_search_%s_%s' % (query, page_no)
	return cache_object(_process, string, 'dummy_arg', False, 24)


def fl_anime_trending(page_no):
	def _process(params):
		data = call_flicklist('/anime/trending', params={'page': page_no, 'per_page': 20}, with_auth=False)
		items, _ = _media_to_fl_list(data, 'tv')
		return items
	string = 'fl_anime_trending_%s' % page_no
	return lists_cache_object(_process, string, {})

def fl_anime_trending_recent(page_no):
	current_year = get_datetime().year
	def _process(params):
		data = call_flicklist('/anime/trending', params={'page': page_no, 'per_page': 20, 'year_min': current_year - 1, 'year_max': current_year}, with_auth=False)
		items, _ = _media_to_fl_list(data, 'tv')
		return items
	string = 'fl_anime_trending_recent_%s' % page_no
	return lists_cache_object(_process, string, {})

def fl_anime_most_watched(page_no):
	def _process(params):
		data = call_flicklist('/anime/trending', params={'page': page_no, 'per_page': 20, 'sort': 'popularity'}, with_auth=False)
		items, _ = _media_to_fl_list(data, 'tv')
		return items
	string = 'fl_anime_most_watched_%s' % page_no
	return lists_cache_object(_process, string, {})

def fl_anime_most_favorited(page_no):
	def _process(params):
		data = call_flicklist('/anime/top-rated', params={'page': page_no, 'per_page': 20}, with_auth=False)
		items, _ = _media_to_fl_list(data, 'tv')
		return items
	string = 'fl_anime_most_favorited_%s' % page_no
	return lists_cache_object(_process, string, {})

def fl_anime_certifications(certification, page_no):
	def _process(params):
		data = call_flicklist('/discover', params={'type': 'tv', 'genre': 16, 'certification': certification, 'page': page_no, 'per_page': 20}, with_auth=False)
		items, _ = _media_to_fl_list(data, 'tv')
		return items
	string = 'fl_anime_certifications_%s_%s' % (certification, page_no)
	return lists_cache_object(_process, string, {})

def fl_anime_search(query, page_no):
	def _process(dummy_arg):
		data = call_flicklist('/search', params={'q': query, 'type': 'tv', 'genre': 'anime', 'page': page_no, 'per_page': 20},
							with_auth=False, pagination=True, page_no=page_no)
		if isinstance(data, tuple):
			raw, page_count = data
		else:
			raw, page_count = data, 1
		items, _ = _extract_paginated(raw)
		fl_items = [_to_fl_show(i) for i in items]
		return (fl_items, str(page_count))
	string = 'fl_anime_search_%s_%s' % (query, page_no)
	return cache_object(_process, string, 'dummy_arg', False, 24)


def fl_recommendations(media_type):
	def _process(params):
		endpoint = '/movies/top-rated' if media_type in ('movie', 'movies') else '/shows/top-rated'
		data = call_flicklist(endpoint, params={'per_page': 50}, with_auth=True)
		mtype = 'movie' if media_type in ('movie', 'movies') else 'tv'
		items, _ = _media_to_fl_list(data, mtype)
		return items
	string = 'fl_recommendations_%s' % media_type
	return flicklist_cache.cache_fl_object(_process, string, {})


def fl_watched_status_mark(action, media, media_id, tvdb_id=0, season=None, episode=None, key='tmdb'):
	"""Mark media as watched/unwatched on FlickList."""
	try:
		if action == 'mark_as_watched':
			if media in ('episode',):
				data = {'media_item_id': int(media_id), 'season_number': int(season), 'episode_number': int(episode)}
				if key == 'tmdb':
					data = {'tmdb_id': int(media_id), 'season_number': int(season), 'episode_number': int(episode)}
				result = call_flicklist('/watched', data=data)
			elif media in ('shows',):
				result = call_flicklist('/watched/batch', data={'tmdb_id': int(media_id), 'scope': 'show'})
			elif media == 'season':
				result = call_flicklist('/watched/batch', data={'tmdb_id': int(media_id), 'scope': 'season', 'season_number': int(season)})
			else:
				data = {'tmdb_id': int(media_id)}
				result = call_flicklist('/watched', data=data)
			return result is not None
		else:
			if media in ('episode',):
				result = call_flicklist('/watched/batch', data={'tmdb_id': int(media_id), 'scope': 'episode',
								'season_number': int(season), 'episode_number': int(episode)}, is_delete=True)
			elif media in ('shows',):
				result = call_flicklist('/watched/batch', data={'tmdb_id': int(media_id), 'scope': 'show'}, is_delete=True)
			elif media == 'season':
				result = call_flicklist('/watched/batch', data={'tmdb_id': int(media_id), 'scope': 'season',
								'season_number': int(season)}, is_delete=True)
			else:
				result = call_flicklist('/watched/batch', data={'tmdb_id': int(media_id), 'scope': 'movie'}, is_delete=True)
			return result is not None
	except Exception as e:
		kodi_utils.logger('FlickList watched_status_mark error', str(e))
		return False

def fl_progress(action, media, media_id, percent, season=None, episode=None, resume_id=None, refresh_trakt=False):
	"""Set or clear playback progress on FlickList."""
	try:
		if action == 'clear_progress':
			if resume_id:
				call_flicklist('/sync/playback/%s' % resume_id, is_delete=True)
		else:
			data = {
				'tmdb_id': int(media_id),
				'media_type': 'episode' if media not in ('movie', 'movies') else 'movie',
				'progress': float(percent),
				'source': 'kodi_flicklist'
			}
			if season is not None:
				data['season'] = int(season)
			if episode is not None:
				data['episode'] = int(episode)
			call_flicklist('/scrobble/event', data=data)
		if refresh_trakt:
			fl_sync_activities()
	except Exception as e:
		kodi_utils.logger('FlickList progress error', str(e))

def fl_official_status(media_type):
	"""Always returns True — FlickList handles all scrobbling directly.
	This function existed in Trakt to check if script.trakt was active.
	Since we ARE the tracker, always return True (meaning: go ahead and track)."""
	return True


def fl_get_hidden_items(list_type):
	"""Get hidden/dropped items from FlickList up-next."""
	try:
		data = call_flicklist('/up-next', params={'include_dropped': 'true'}, with_auth=True)
		if data and isinstance(data, list):
			dropped = [item.get('tmdb_id') for item in data if item.get('dropped', False)]
			return dropped
	except:
		pass
	return []

def hide_unhide_progress_items(params):
	"""Drop or undrop a show from FlickList up-next."""
	action, media_type, media_id, list_type = params['action'], params['media_type'], params['media_id'], params['section']
	try:
		if action == 'drop':
			call_flicklist('/up-next/%s/drop' % media_id, method='post')
		else:
			call_flicklist('/up-next/%s/undrop' % media_id, method='post')
	except:
		pass
	fl_sync_activities()
	kodi_utils.kodi_refresh()


def fl_collection_lists(media_type, list_type=None):
	"""FlickList watchlist with status=watching serves as 'collection'."""
	data = fl_fetch_collection_watchlist('collection', media_type)
	if list_type == 'recent':
		data.sort(key=lambda k: k.get('collected_at', ''), reverse=True)
		data = data[:20]
	return data

def fl_watchlist_lists(media_type, list_type=None):
	data = fl_fetch_collection_watchlist('watchlist', media_type)
	if list_type == 'recent':
		data.sort(key=lambda k: k.get('collected_at', ''), reverse=True)
		data = data[:20]
	return data

def fl_collection(media_type, dummy_arg):
	data = fl_fetch_collection_watchlist('collection', media_type)
	sort_order = settings.lists_sort_order('collection')
	if sort_order == 0:
		data = sort_for_article(data, 'title', settings.ignore_articles())
	elif sort_order == 1:
		data.sort(key=lambda k: k.get('collected_at', ''), reverse=True)
	else:
		data.sort(key=lambda k: k.get('released', ''), reverse=True)
	return data

def fl_watchlist(media_type, dummy_arg):
	data = fl_fetch_collection_watchlist('watchlist', media_type)
	if not settings.show_unaired_watchlist():
		current_date = get_datetime()
		str_format = '%Y-%m-%d' if media_type in ('movie', 'movies') else '%Y-%m-%dT%H:%M:%S.%fZ'
		data = [i for i in data if i.get('released', None) and js2date(i.get('released'), str_format, remove_time=True) <= current_date]
	sort_order = settings.lists_sort_order('watchlist')
	if sort_order == 0:
		data = sort_for_article(data, 'title', settings.ignore_articles())
	elif sort_order == 1:
		data.sort(key=lambda k: k.get('collected_at', ''), reverse=True)
	else:
		data.sort(key=lambda k: k.get('released', ''), reverse=True)
	return data

def fl_fetch_collection_watchlist(list_type, media_type):
	"""Fetch watchlist from FlickList and transform to Trakt-compatible shape."""
	def _process(params):
		data = call_flicklist('/user/watchlist', params={'status': 'watching' if list_type == 'collection' else None}, with_auth=True)
		if not data:
			return []
		items = data if isinstance(data, list) else data.get('results', data.get('items', []))
		results = []
		for item in items:
			mtype = item.get('media_type', 'movie')
			if media_type in ('movie', 'movies') and mtype != 'movie':
				continue
			if media_type in ('show', 'shows', 'tvshow') and mtype not in ('tv', 'show'):
				continue
			results.append({
				'media_ids': {
					'tmdb': item.get('tmdb_id', ''),
					'imdb': item.get('imdb_id', ''),
					'tvdb': item.get('tvdb_id', '')
				},
				'title': item.get('title', ''),
				'collected_at': item.get('updated_at', item.get('created_at', '')),
				'released': item.get('year', '')
			})
		return results
	if media_type in ('movie', 'movies'):
		string_insert = 'movie'
	else:
		string_insert = 'tvshow'
	string = 'fl_%s_%s' % (list_type, string_insert)
	return flicklist_cache.cache_fl_object(_process, string, {})

def add_to_list(user, slug, data):
	"""Add media to a FlickList user list."""
	items = []
	for key in ('movies', 'shows'):
		for item in data.get(key, []):
			tmdb_id = item.get('ids', {}).get('tmdb')
			if tmdb_id:
				items.append({'tmdb_id': tmdb_id})
	if not items:
		return kodi_utils.notification('Error', 3000)
	for item in items:
		result = call_flicklist('/user/lists/%s/items' % slug, data={'media_item_id': item['tmdb_id']})
	kodi_utils.notification('Success', 3000)
	fl_sync_activities()
	return result

def remove_from_list(user, slug, data):
	"""Remove media from a FlickList user list."""
	items = []
	for key in ('movies', 'shows'):
		for item in data.get(key, []):
			tmdb_id = item.get('ids', {}).get('tmdb')
			if tmdb_id:
				items.append(tmdb_id)
	for tmdb_id in items:
		call_flicklist('/user/lists/%s/items/%s' % (slug, tmdb_id), is_delete=True)
	kodi_utils.notification('Success', 3000)
	fl_sync_activities()
	if kodi_utils.path_check('my_lists') or kodi_utils.external():
		kodi_utils.kodi_refresh()

def add_to_watchlist(data):
	"""Add to FlickList watchlist."""
	for key in ('movies', 'shows'):
		for item in data.get(key, []):
			tmdb_id = item.get('ids', {}).get('tmdb')
			if tmdb_id:
				result = call_flicklist('/user/watchlist', data={'media_id': tmdb_id})
				if result is None:
					return kodi_utils.notification('Error', 3000)
	kodi_utils.notification('Success', 3000)
	fl_sync_activities()

def remove_from_watchlist(data):
	"""Remove from FlickList watchlist."""
	for key in ('movies', 'shows'):
		for item in data.get(key, []):
			tmdb_id = item.get('ids', {}).get('tmdb')
			if tmdb_id:
				call_flicklist('/user/watchlist/%s' % tmdb_id, is_delete=True)
	kodi_utils.notification('Success', 3000)
	fl_sync_activities()
	if kodi_utils.path_check('fl_watchlist') or kodi_utils.external():
		kodi_utils.kodi_refresh()

def add_to_collection(data):
	"""FlickList doesn't have a separate collection — map to watchlist with status=watching."""
	return add_to_watchlist(data)

def remove_from_collection(data):
	return remove_from_watchlist(data)


def fl_favorites(media_type, dummy_arg):
	def _process(params):
		data = call_flicklist('/user/favorites', with_auth=True)
		if not data:
			return []
		items = data if isinstance(data, list) else data.get('results', data.get('items', []))
		results = []
		mtype_filter = 'movie' if media_type in ('movie', 'movies') else 'tv'
		for item in items:
			if item.get('media_type', '') == mtype_filter or not item.get('media_type'):
				results.append({
					'media_ids': {
						'tmdb': item.get('tmdb_id', ''),
						'imdb': item.get('imdb_id', ''),
						'tvdb': item.get('tvdb_id', '')
					}
				})
		return results
	media_type_key = 'movies' if media_type in ('movie', 'movies') else 'shows'
	string = 'fl_favorites_%s' % media_type_key
	return flicklist_cache.cache_fl_object(_process, string, {})

def fl_get_lists(list_type, page_no='1'):
	"""Get user's FlickList lists."""
	if list_type in ('trending', 'popular'):
		return []
	else:
		def _process(params):
			data = call_flicklist('/user/lists', with_auth=True)
			if not data:
				return []
			items = data if isinstance(data, list) else data.get('results', data.get('items', []))
			results = []
			for item in items:
				results.append({
					'name': item.get('name', item.get('title', '')),
					'ids': {
						'slug': str(item.get('id', '')),
						'trakt': item.get('id', 0)
					},
					'user': {'ids': {'slug': item.get('user_id', '')}},
					'item_count': item.get('item_count', 0),
					'privacy': item.get('privacy', 'private'),
					'sort_by': item.get('sort_by', 'rank'),
					'sort_how': item.get('sort_how', 'asc')
				})
			return results
		if list_type == 'my_lists':
			string = 'fl_my_lists'
		else:
			string = 'fl_liked_lists'
		return flicklist_cache.cache_fl_object(_process, string, {})

def get_fl_list_contents(list_type, user, slug, with_auth, list_id=None, sort_by='default', sort_how='default'):
	"""Get items from a FlickList list."""
	skip_sort = sort_by == 'skip'
	custom_sort = not skip_sort and sort_by != 'default'
	def _fetch(params):
		lid = list_id or slug
		data = call_flicklist('/user/lists/%s/items' % lid, with_auth=True)
		if not data:
			return []
		items = data if isinstance(data, list) else data.get('results', data.get('items', []))
		results = []
		for c, item in enumerate(items):
			try:
				mtype = item.get('media_type', 'movie')
				if mtype in ('movie',):
					result = {
						'media_ids': {
							'tmdb': item.get('tmdb_id', ''),
							'imdb': item.get('imdb_id', ''),
							'tvdb': ''
						},
						'title': item.get('title', ''),
						'type': 'movie',
						'order': c,
						'released': item.get('year', ''),
						'media_type': 'movie'
					}
				elif mtype in ('tv', 'show'):
					result = {
						'media_ids': {
							'tmdb': item.get('tmdb_id', ''),
							'imdb': item.get('imdb_id', ''),
							'tvdb': item.get('tvdb_id', '')
						},
						'title': item.get('title', ''),
						'type': 'show',
						'order': c,
						'released': item.get('year', ''),
						'media_type': 'show'
					}
				else:
					continue
				results.append(result)
			except:
				pass
		return results
	string = 'fl_list_contents_%s_%s_%s' % (list_type, user, slug)
	data = flicklist_cache.cache_fl_object(_fetch, string, {})
	if not skip_sort and data:
		if not custom_sort and isinstance(data, dict):
			sort_by = data.get('sort_by', 'rank')
			sort_how = data.get('sort_how', 'asc')
			data = data.get('data', data)
		if isinstance(data, list):
			data = sort_list(sort_by if sort_by != 'default' else 'rank', sort_how if sort_how != 'default' else 'asc', data, settings.ignore_articles())
	return data if isinstance(data, list) else []

def get_fl_list_selection(included_lists):
	"""List selection dialog for FlickList lists."""
	def default_lists():
		return [
			{'name': 'Movies Watchlist', 'display': '[B][I]MOVIES WATCHLIST [/I][/B]', 'user': 'Watchlist', 'slug': 'Watchlist', 'list_type': 'watchlist', 'media_type': 'movie'},
			{'name': 'TV Show Watchlist', 'display': '[B][I]TV SHOW WATCHLIST [/I][/B]', 'user': 'Watchlist', 'slug': 'Watchlist', 'list_type': 'watchlist', 'media_type': 'show'}
		]
	def personal_lists():
		my_lists = fl_get_lists('my_lists')
		_lists = [{'name': item['name'], 'display': '[B]PERSONAL:[/B] [I]%s[/I]' % item['name'].upper(), 'user': item['user']['ids']['slug'],
			'slug': item['ids']['slug'], 'list_type': 'my_lists', 'list_id': item['ids']['trakt'], 'item_count': item.get('item_count', 0)} for item in my_lists]
		_lists.sort(key=lambda k: k['name'])
		return _lists
	def liked_lists():
		return []
	list_dict = {'default': default_lists, 'personal': personal_lists, 'liked': liked_lists}
	used_lists = []
	for list_type in included_lists:
		used_lists.extend(list_dict[list_type]())
	list_items = [{'line1': '%s%s' % (item['display'], ' [I](x%02d)[/I]' % item['item_count'] if 'item_count' in item else '')} for item in used_lists]
	kwargs = {'items': json.dumps(list_items), 'heading': 'Select', 'narrow_window': 'true'}
	selection = kodi_utils.select_dialog(used_lists, **kwargs)
	if selection is None:
		return None
	return selection

def make_new_fl_list(params):
	"""Create a new FlickList list."""
	list_title = kodi_utils.kodi_dialog().input('')
	if not list_title:
		return
	list_name = unquote(list_title)
	data = {'name': list_name, 'privacy': 'private'}
	call_flicklist('/user/lists', data=data)
	fl_sync_activities()
	kodi_utils.notification('Success', 3000)
	kodi_utils.kodi_refresh()

def delete_fl_list(params):
	"""Delete a FlickList list."""
	list_slug = params['list_slug']
	if not kodi_utils.confirm_dialog():
		return
	call_flicklist('/user/lists/%s' % list_slug, is_delete=True)
	fl_sync_activities()
	kodi_utils.notification('Success', 3000)
	kodi_utils.kodi_refresh()

def fl_like_a_list(params):
	"""FlickList doesn't have list liking yet — no-op."""
	kodi_utils.notification('Not available yet', 3000)
	return False

def fl_search_lists(search_title, page_no):
	"""FlickList doesn't have public list search yet — return empty."""
	return []

def fl_lists_with_media(media_type, imdb_id):
	"""FlickList doesn't have 'lists containing this media' yet — return empty."""
	return []


def fl_indicators_movies():
	"""Fetch watched movies from FlickList and store in local cache."""
	def _process(item):
		tmdb_id = item.get('tmdb_id')
		if not tmdb_id:
			return
		title = item.get('title', '')
		watched_at = item.get('watched_at', item.get('created_at', ''))
		insert_append(('movie', tmdb_id, '', '', watched_at, title))
	insert_list = []
	insert_append = insert_list.append
	data = call_flicklist('/scrobble/history', params={'media_type': 'movie', 'matched_only': 'true', 'per_page': 5000}, with_auth=True)
	if not data:
		return
	items = data.get('results', data.get('items', [])) if isinstance(data, dict) else data
	threads = list(make_thread_list(_process, items))
	[i.join() for i in threads]
	flicklist_cache.fl_watched_cache.set_bulk_movie_watched(insert_list)

def fl_indicators_tv():
	"""Fetch watched TV episodes from FlickList and store in local cache."""
	def _process(item):
		tmdb_id = item.get('tmdb_id')
		if not tmdb_id:
			return
		title = item.get('title', '')
		season = item.get('season_number', 0)
		episode = item.get('episode_number', 0)
		watched_at = item.get('watched_at', item.get('created_at', ''))
		if season and season > 0:
			insert_append(('episode', tmdb_id, season, episode, watched_at, title))
	insert_list = []
	insert_append = insert_list.append
	data = call_flicklist('/scrobble/history', params={'media_type': 'tv', 'matched_only': 'true', 'per_page': 5000}, with_auth=True)
	if not data:
		return
	items = data.get('results', data.get('items', [])) if isinstance(data, dict) else data
	threads = list(make_thread_list(_process, items))
	[i.join() for i in threads]
	flicklist_cache.fl_watched_cache.set_bulk_tvshow_watched(insert_list)


def fl_playback_progress():
	"""Get in-progress items from FlickList."""
	data = call_flicklist('/sync/playback', with_auth=True)
	if not data:
		return []
	items = data if isinstance(data, list) else data.get('results', data.get('items', []))
	results = []
	for item in items:
		mtype = item.get('media_type', 'movie')
		progress_item = {
			'progress': item.get('progress', 0),
			'paused_at': item.get('updated_at', item.get('paused_at', '')),
			'id': item.get('id', 0),
			'type': mtype
		}
		if mtype in ('movie',):
			progress_item['movie'] = {
				'title': item.get('title', ''),
				'ids': {'tmdb': item.get('tmdb_id', 0), 'imdb': item.get('imdb_id', ''), 'tvdb': 0}
			}
		else:
			progress_item['show'] = {
				'title': item.get('title', item.get('show_title', '')),
				'ids': {'tmdb': item.get('tmdb_id', 0), 'imdb': item.get('imdb_id', ''), 'tvdb': item.get('tvdb_id', 0)}
			}
			progress_item['episode'] = {
				'season': item.get('season_number', item.get('season', 0)),
				'number': item.get('episode_number', item.get('episode', 0))
			}
		results.append(progress_item)
	return results

def fl_progress_movies(progress_info):
	"""Process movie progress and store in cache."""
	def _process(item):
		tmdb_id = get_fl_movie_id(item['movie']['ids'])
		if not tmdb_id:
			return
		obj = ('movie', str(tmdb_id), '', '', str(round(item['progress'], 1)), 0, item['paused_at'], item['id'], item['movie']['title'])
		insert_append(obj)
	insert_list = []
	insert_append = insert_list.append
	progress_items = [i for i in progress_info if i['type'] == 'movie' and i['progress'] > 1]
	if not progress_items:
		return
	threads = list(make_thread_list(_process, progress_items))
	[i.join() for i in threads]
	flicklist_cache.fl_watched_cache.set_bulk_movie_progress(insert_list)

def fl_progress_tv(progress_info):
	"""Process TV progress and store in cache."""
	def _process_tmdb_ids(item):
		tmdb_id = get_fl_tvshow_id(item['ids'])
		tmdb_list_append((tmdb_id, item['title']))
	def _process():
		for item in tmdb_list:
			try:
				tmdb_id = item[0]
				if not tmdb_id:
					continue
				title = item[1]
				for p_item in progress_items:
					if p_item['show']['title'] == title:
						season = p_item['episode']['season']
						if season > 0:
							yield ('episode', str(tmdb_id), season, p_item['episode']['number'], str(round(p_item['progress'], 1)),
									0, p_item['paused_at'], p_item['id'], p_item['show']['title'])
			except:
				pass
	tmdb_list = []
	tmdb_list_append = tmdb_list.append
	progress_items = [i for i in progress_info if i['type'] == 'episode' and i['progress'] > 1]
	if not progress_items:
		return
	all_shows = [i['show'] for i in progress_items]
	all_shows = [i for n, i in enumerate(all_shows) if not i in all_shows[n + 1:]]
	threads = list(make_thread_list(_process_tmdb_ids, all_shows))
	[i.join() for i in threads]
	insert_list = list(_process())
	flicklist_cache.fl_watched_cache.set_bulk_tvshow_progress(insert_list)


def fl_get_my_calendar(recently_aired, current_date):
	def _process(dummy):
		data = call_flicklist('/calendar/my/shows/%s/%s' % (start, finish), with_auth=True)
		if not data:
			return []
		items = data if isinstance(data, list) else data.get('results', data.get('items', []))
		results = []
		for item in items:
			results.append({
				'sort_title': '%s s%s e%s' % (item.get('show_title', item.get('title', '')),
										str(item.get('season_number', item.get('season', 0))).zfill(2),
										str(item.get('episode_number', item.get('episode', 0))).zfill(2)),
				'media_ids': {
					'tmdb': item.get('tmdb_id', 0),
					'imdb': item.get('imdb_id', ''),
					'tvdb': item.get('tvdb_id', 0)
				},
				'season': item.get('season_number', item.get('season', 0)),
				'episode': item.get('episode_number', item.get('episode', 0)),
				'first_aired': item.get('air_date', item.get('first_aired', ''))
			})
		results = [i for n, i in enumerate(results) if i not in results[n + 1:]]
		return results
	start, finish = fl_calendar_days(recently_aired, current_date)
	string = 'fl_get_my_calendar_%s_%s' % (start, finish)
	return flicklist_cache.cache_fl_object(_process, string, 'dummy')

def fl_calendar_days(recently_aired, current_date):
	if recently_aired:
		start = (current_date - timedelta(days=14)).strftime('%Y-%m-%d')
		finish = '14'
	else:
		previous_days = int(get_setting('fenlightfl.flicklist.calendar_previous_days', '7'))
		future_days = int(get_setting('fenlightfl.flicklist.calendar_future_days', '7'))
		start = (current_date - timedelta(days=previous_days)).strftime('%Y-%m-%d')
		finish = str(previous_days + future_days)
	return start, finish


def fl_comments(media_type, imdb_id):
	"""FlickList doesn't have comments yet — return empty."""
	return []


def scrobble_start(media_type, tmdb_id, season=None, episode=None, duration=None):
	"""Notify FlickList that playback has started."""
	data = {
		'tmdb_id': int(tmdb_id),
		'media_type': 'episode' if media_type not in ('movie', 'movies') else 'movie',
		'progress': 0.0,
		'source': 'kodi_flicklist',
		'event': 'start'
	}
	if season is not None:
		data['season'] = int(season)
	if episode is not None:
		data['episode'] = int(episode)
	if duration is not None:
		data['duration'] = int(duration)
	try:
		call_flicklist('/scrobble/event', data=data)
	except:
		pass

def scrobble_pause(media_type, tmdb_id, progress, season=None, episode=None):
	"""Notify FlickList that playback has been paused."""
	data = {
		'tmdb_id': int(tmdb_id),
		'media_type': 'episode' if media_type not in ('movie', 'movies') else 'movie',
		'progress': float(progress),
		'source': 'kodi_flicklist',
		'event': 'pause'
	}
	if season is not None:
		data['season'] = int(season)
	if episode is not None:
		data['episode'] = int(episode)
	try:
		call_flicklist('/scrobble/event', data=data)
	except:
		pass

def scrobble_stop(media_type, tmdb_id, progress, season=None, episode=None):
	"""Notify FlickList that playback has stopped."""
	data = {
		'tmdb_id': int(tmdb_id),
		'media_type': 'episode' if media_type not in ('movie', 'movies') else 'movie',
		'progress': float(progress),
		'source': 'kodi_flicklist',
		'event': 'stop'
	}
	if season is not None:
		data['season'] = int(season)
	if episode is not None:
		data['episode'] = int(episode)
	try:
		call_flicklist('/scrobble/event', data=data)
	except:
		pass

def scrobble_heartbeat(media_type, tmdb_id, progress, current_time=None, duration=None, season=None, episode=None):
	"""Send a 30-second heartbeat during playback."""
	data = {
		'tmdb_id': int(tmdb_id),
		'media_type': 'episode' if media_type not in ('movie', 'movies') else 'movie',
		'progress': float(progress),
		'source': 'kodi_flicklist',
		'event': 'heartbeat',
		'timestamp': get_datetime().strftime('%Y-%m-%dT%H:%M:%S.000Z')
	}
	if season is not None:
		data['season'] = int(season)
	if episode is not None:
		data['episode'] = int(episode)
	if current_time is not None:
		data['current_time'] = int(current_time)
	if duration is not None:
		data['duration'] = int(duration)
	try:
		call_flicklist('/scrobble/event', data=data)
	except:
		pass


def fl_get_activity():
	"""Get last activity timestamps from FlickList."""
	data = call_flicklist('/sync/last-activities', with_auth=True)
	if data:
		return data
	return flicklist_cache.default_activities()

def fl_sync_activities(force_update=False):
	"""Sync watched/progress/lists data from FlickList."""
	def clear_properties(media_type):
		for item in ((True, True), (True, False), (False, True), (False, False)):
			kodi_utils.clear_property('1_%s_%s_%s_watched' % (media_type, item[0], item[1]))
	def _get_timestamp(date_time):
		return int(time.mktime(date_time.timetuple()))
	def _compare(latest, cached):
		try:
			result = _get_timestamp(js2date(latest, '%Y-%m-%dT%H:%M:%S.%fZ')) > _get_timestamp(js2date(cached, '%Y-%m-%dT%H:%M:%S.%fZ'))
		except:
			result = True
		return result
	def _check_daily_expiry():
		return int(time.time()) >= int(get_setting('fenlightfl.flicklist.next_daily_clear', '0'))
	fl_refresh_token()
	if force_update:
		flicklist_cache.clear_all_fl_cache_data(silent=True, refresh=False)
	elif _check_daily_expiry():
		flicklist_cache.clear_daily_cache()
		set_setting('flicklist.next_daily_clear', str(int(time.time()) + (24 * 3600)))
	if not settings.flicklist_user_active() and not force_update:
		return 'no account'
	try:
		latest = fl_get_activity()
	except:
		return 'failed'
	cached = flicklist_cache.reset_activity(latest)
	fallback_date = '2020-01-01T00:00:01.000Z'
	if not _compare(latest.get('all', fallback_date), cached.get('all', fallback_date)):
		return 'not needed'
	lists_actions, refresh_movies_progress, refresh_shows_progress = [], False, False
	cached_movies = cached.get('movies', {})
	latest_movies = latest.get('movies', {})
	cached_shows = cached.get('shows', {})
	latest_shows = latest.get('shows', {})
	cached_episodes = cached.get('episodes', {})
	latest_episodes = latest.get('episodes', {})
	cached_lists = cached.get('lists', {})
	latest_lists = latest.get('lists', {})
	if _compare(latest.get('recommendations', fallback_date), cached.get('recommendations', fallback_date)):
		flicklist_cache.clear_fl_recommendations()
	if _compare(latest.get('favorites', fallback_date), cached.get('favorites', fallback_date)):
		flicklist_cache.clear_fl_favorites()
	if _compare(latest_movies.get('collected_at', fallback_date), cached_movies.get('collected_at', fallback_date)):
		flicklist_cache.clear_fl_collection_watchlist_data('collection', 'movie')
	if _compare(latest_episodes.get('collected_at', fallback_date), cached_episodes.get('collected_at', fallback_date)):
		flicklist_cache.clear_fl_collection_watchlist_data('collection', 'tvshow')
	if _compare(latest_movies.get('watchlisted_at', fallback_date), cached_movies.get('watchlisted_at', fallback_date)):
		flicklist_cache.clear_fl_collection_watchlist_data('watchlist', 'movie')
	if _compare(latest_shows.get('watchlisted_at', fallback_date), cached_shows.get('watchlisted_at', fallback_date)):
		flicklist_cache.clear_fl_collection_watchlist_data('watchlist', 'tvshow')
	if _compare(latest_shows.get('dropped_at', fallback_date), cached_shows.get('dropped_at', fallback_date)):
		clear_properties('episode')
		flicklist_cache.clear_fl_hidden_data('dropped')
	if _compare(latest_movies.get('watched_at', fallback_date), cached_movies.get('watched_at', fallback_date)):
		clear_properties('movie')
		fl_indicators_movies()
	if _compare(latest_episodes.get('watched_at', fallback_date), cached_episodes.get('watched_at', fallback_date)):
		clear_properties('episode')
		fl_indicators_tv()
	if _compare(latest_movies.get('paused_at', fallback_date), cached_movies.get('paused_at', fallback_date)):
		refresh_movies_progress = True
	if _compare(latest_episodes.get('paused_at', fallback_date), cached_episodes.get('paused_at', fallback_date)):
		refresh_shows_progress = True
	if _compare(latest_lists.get('updated_at', fallback_date), cached_lists.get('updated_at', fallback_date)):
		lists_actions.append('my_lists')
	if _compare(latest_lists.get('liked_at', fallback_date), cached_lists.get('liked_at', fallback_date)):
		lists_actions.append('liked_lists')
	if refresh_movies_progress or refresh_shows_progress:
		progress_info = fl_playback_progress()
		if refresh_movies_progress:
			clear_properties('movie')
			fl_progress_movies(progress_info)
		if refresh_shows_progress:
			clear_properties('episode')
			fl_progress_tv(progress_info)
	if lists_actions:
		for item in lists_actions:
			flicklist_cache.clear_fl_list_data(item)
			flicklist_cache.clear_fl_list_contents_data(item)
	return 'success'


def get_fl_movie_id(item):
	if item.get('tmdb'):
		return item['tmdb']
	tmdb_id = None
	api_key = settings.tmdb_api_key()
	if item.get('imdb'):
		try:
			meta = movie_meta_external_id('imdb_id', item['imdb'], api_key)
			tmdb_id = meta['id']
		except:
			pass
	return tmdb_id

def get_fl_tvshow_id(item):
	if item.get('tmdb'):
		return item['tmdb']
	tmdb_id = None
	api_key = settings.tmdb_api_key()
	if item.get('imdb'):
		try:
			meta = tvshow_meta_external_id('imdb_id', item['imdb'], api_key)
			tmdb_id = meta['id']
		except:
			tmdb_id = None
	if not tmdb_id:
		if item.get('tvdb'):
			try:
				meta = tvshow_meta_external_id('tvdb_id', item['tvdb'], api_key)
				tmdb_id = meta['id']
			except:
				tmdb_id = None
	return tmdb_id

def make_fl_slug(name):
	"""Generate a URL slug from a title."""
	import re
	name = name.strip()
	name = name.lower()
	name = re.sub('[^a-z0-9_]', '-', name)
	name = re.sub('--+', '-', name)
	return name
