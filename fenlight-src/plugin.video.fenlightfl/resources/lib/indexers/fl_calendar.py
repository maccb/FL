
import sys
import json
from datetime import datetime, timedelta
from modules import kodi_utils, settings, watched_status as ws
from apis.flicklist_api import call_flicklist
from caches.settings_cache import get_setting

TMDB_IMAGE_URL = 'https://image.tmdb.org/t/p/%s%s'


def _fetch_calendar(previous_days=7, future_days=14):
	"""Fetch user's personal calendar from FlickList API.
	Returns list of {date, items: [...CalendarEpisode]} or empty list."""
	start = (datetime.now() - timedelta(days=previous_days)).strftime('%Y-%m-%d')
	total_days = str(previous_days + future_days)
	try:
		data = call_flicklist('/calendar/my/shows/%s/%s' % (start, total_days), with_auth=True)
		if not data or not isinstance(data, dict):
			return None
		return data.get('days', [])
	except Exception as e:
		kodi_utils.logger('FL Calendar', 'API error: %s' % str(e))
		return None

def _is_authenticated():
	"""Check if user has a FlickList token."""
	token = get_setting('fenlightfl.flicklist.token')
	return token and token not in ('0', 'empty_setting', '')


def _format_day_label(date_str, ep_count):
	"""Format: 'TODAY · 3 episodes' or 'Wed Feb 19 · 5 episodes' """
	date_obj = datetime.strptime(date_str, '%Y-%m-%d')
	today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
	tomorrow = today + timedelta(days=1)
	if date_obj.date() == today.date():
		day_name = '[COLOR ff22d3a7]TODAY[/COLOR]'
	elif date_obj.date() == tomorrow.date():
		day_name = '[COLOR ffffcc00]TOMORROW[/COLOR]'
	else:
		day_name = date_obj.strftime('%a %b %d').upper()
	ep_word = 'episode' if ep_count == 1 else 'episodes'
	return '%s  ·  %d %s' % (day_name, ep_count, ep_word)


def _format_episode_label(item):
	"""Format: 'Show Title · S03E05 · Episode Title' """
	s_num = str(item.get('season_number', 0)).zfill(2)
	e_num = str(item.get('episode_number', 0)).zfill(2)
	parts = [
		'[B]%s[/B]' % item.get('show_title', 'Unknown'),
		'S%sE%s' % (s_num, e_num),
	]
	ep_title = item.get('episode_title')
	if ep_title and ep_title != 'Episode %s' % item.get('episode_number', 0):
		parts.append(ep_title)
	network = item.get('primary_network')
	if network:
		parts.append('[COLOR ff888888]%s[/COLOR]' % network)
	return '  ·  '.join(parts)


def _format_episode_plot(item):
	"""Plot shown in info panel"""
	s_num = str(item.get('season_number', 0)).zfill(2)
	e_num = str(item.get('episode_number', 0)).zfill(2)
	lines = [
		'[B]%s[/B]' % item.get('show_title', 'Unknown'),
		'Season %s, Episode %s' % (s_num, e_num),
	]
	ep_title = item.get('episode_title')
	if ep_title:
		lines.append(ep_title)
	network = item.get('primary_network')
	if network:
		lines.append('')
		lines.append('[COLOR ff22d3a7]%s[/COLOR]' % network)
	runtime = item.get('runtime')
	if runtime:
		lines.append('%d min' % runtime)
	return '\n'.join(lines)


def _get_poster(item, size='w342'):
	"""Build TMDB poster URL from poster_path, or return None."""
	path = item.get('poster_path')
	if path:
		return TMDB_IMAGE_URL % (size, path)
	return None


def _get_still(item, size='w300'):
	"""Build TMDB still URL from still_path, or return None."""
	path = item.get('still_path')
	if path:
		return TMDB_IMAGE_URL % (size, path)
	return None


def build_calendar_days(params):
	"""Root calendar view: 7-day sliding window with Previous/Next Week nav.
	Offset 0 = current week (yesterday through 5 days ahead).
	Negative offset = past weeks, positive = future weeks."""
	handle = int(sys.argv[1])
	build_url = kodi_utils.build_url
	make_listitem = kodi_utils.make_listitem
	add_items = kodi_utils.add_items
	fanart = kodi_utils.get_addon_fanart()
	offset = int(params.get('offset', 0))

	if not _is_authenticated():
		listitem = make_listitem()
		listitem.setLabel('[COLOR ff22d3a7]Log in to FlickList to see your calendar[/COLOR]')
		listitem.setArt({'icon': kodi_utils.get_icon('calender'), 'fanart': fanart})
		info_tag = listitem.getVideoInfoTag(True)
		info_tag.setPlot('Go to Tools > FL Account to authorize your device.\nThen add shows to your calendar on flicklist.tv')
		url = build_url({'mode': 'navigator.flicklist_authorize'})
		add_items(handle, [(url, listitem, False)])
		kodi_utils.set_content(handle, '')
		kodi_utils.set_category(handle, 'FL Calendar')
		kodi_utils.end_directory(handle)
		return

	window_start = datetime.now() + timedelta(days=offset - 1)
	window_end = datetime.now() + timedelta(days=offset + 5)
	start_str = window_start.strftime('%Y-%m-%d')
	end_str = window_end.strftime('%Y-%m-%d')
	days_back = max(0, (datetime.now() - window_start).days + 1)
	days_fwd = max(0, (window_end - datetime.now()).days + 1)
	calendar_days = _fetch_calendar(previous_days=days_back, future_days=days_fwd)
	if calendar_days is None:
		listitem = make_listitem()
		listitem.setLabel('[COLOR ffff4444]Could not load calendar - check connection[/COLOR]')
		listitem.setArt({'icon': kodi_utils.get_icon('calender'), 'fanart': fanart})
		add_items(handle, [(build_url({}), listitem, False)])
		kodi_utils.set_content(handle, '')
		kodi_utils.set_category(handle, 'FL Calendar')
		kodi_utils.end_directory(handle)
		return

	calendar_days = [d for d in calendar_days if start_str <= d.get('date', '') <= end_str]

	items = []

	if offset > -84:
		prev_li = make_listitem()
		prev_li.setLabel('[COLOR ff22d3a7][B]<  Previous Week[/B][/COLOR]')
		prev_li.setArt({'icon': kodi_utils.get_icon('calender'), 'fanart': fanart})
		prev_li.getVideoInfoTag(True).setPlot('Show the previous 7 days')
		items.append((build_url({'mode': 'fl_calendar.build_calendar_days', 'offset': offset - 7}), prev_li, True))

	day_count = 0
	for day in calendar_days:
		day_items = day.get('items', [])
		ep_count = len(day_items)
		if ep_count == 0:
			continue
		day_count += 1
		date_str = day['date']
		label = _format_day_label(date_str, ep_count)
		show_names = list(dict.fromkeys(i.get('show_title', '') for i in day_items))
		plot = '\n'.join(show_names[:5])
		if len(show_names) > 5:
			plot += '\n+ %d more...' % (len(show_names) - 5)
		url = build_url({'mode': 'fl_calendar.build_calendar_day', 'date': date_str})
		listitem = make_listitem()
		listitem.setLabel(label)
		first_poster = None
		for di in day_items:
			first_poster = _get_poster(di)
			if first_poster: break
		icon = first_poster or kodi_utils.get_icon('calender')
		listitem.setArt({'icon': icon, 'poster': icon, 'thumb': icon, 'fanart': fanart, 'banner': icon})
		listitem.getVideoInfoTag(True).setPlot(plot)
		items.append((url, listitem, True))

	if day_count == 0:
		empty_li = make_listitem()
		empty_li.setLabel('[COLOR ff888888]No episodes this week[/COLOR]')
		empty_li.setArt({'icon': kodi_utils.get_icon('calender'), 'fanart': fanart})
		items.append((build_url({}), empty_li, False))

	if offset < 28:
		next_li = make_listitem()
		next_li.setLabel('[COLOR ff22d3a7][B]Next Week  >[/B][/COLOR]')
		next_li.setArt({'icon': kodi_utils.get_icon('calender'), 'fanart': fanart})
		next_li.getVideoInfoTag(True).setPlot('Show the next 7 days')
		items.append((build_url({'mode': 'fl_calendar.build_calendar_days', 'offset': offset + 7}), next_li, True))

	range_label = '%s - %s' % (window_start.strftime('%b %d'), window_end.strftime('%b %d'))
	add_items(handle, items)
	kodi_utils.set_content(handle, '')
	kodi_utils.set_category(handle, range_label)
	kodi_utils.end_directory(handle)
	kodi_utils.set_view_mode('view.main', '')

def build_calendar_day(params):
	"""Episode list for a specific day. Re-fetches from API to get fresh data."""
	handle = int(sys.argv[1])
	build_url = kodi_utils.build_url
	make_listitem = kodi_utils.make_listitem
	add_items = kodi_utils.add_items
	fanart = kodi_utils.get_addon_fanart()

	target_date = params.get('date', '')

	try:
		target_dt = datetime.strptime(target_date, '%Y-%m-%d')
		now = datetime.now()
		diff_days = (now - target_dt).days
		if diff_days > 0:
			prev_days = diff_days + 2
			fwd_days = 1
		else:
			prev_days = 1
			fwd_days = abs(diff_days) + 2
	except:
		prev_days = 7
		fwd_days = 14
	calendar_days = _fetch_calendar(previous_days=prev_days, future_days=fwd_days)
	day_data = None
	if calendar_days:
		for day in calendar_days:
			if day.get('date') == target_date:
				day_data = day
				break

	if not day_data or not day_data.get('items'):
		listitem = make_listitem()
		listitem.setLabel('[COLOR ff888888]No episodes for this day[/COLOR]')
		listitem.setArt({'icon': kodi_utils.get_icon('calender'), 'fanart': fanart})
		add_items(handle, [(build_url({}), listitem, False)])
		kodi_utils.set_content(handle, 'episodes')
		kodi_utils.end_directory(handle)
		return

	items = []

	playback_key = settings.playback_key()
	play_mode = 'playback.%s' % playback_key
	try:
		watched_indicators = settings.watched_indicators()
		watched_db = ws.get_database(watched_indicators)
		show_ids = set(ep.get('tmdb_id') for ep in day_data['items'] if ep.get('tmdb_id'))
		watched_cache = {}
		for sid in show_ids:
			try:
				info = ws.watched_info_episode(str(sid), watched_db)
				watched_cache[sid] = set(info) if info else set()
			except: watched_cache[sid] = set()
	except: watched_cache = {}
	for ep in day_data['items']:
		label = _format_episode_label(ep)
		plot = _format_episode_plot(ep)

		season_num = ep.get('season_number', 1)
		episode_num = ep.get('episode_number', 1)
		tmdb_id = ep.get('tmdb_id', 0)
		url_params = {
			'mode': play_mode,
			'media_type': 'episode',
			'tmdb_id': tmdb_id,
			'season': season_num,
			'episode': episode_num,
			playback_key: playback_key,
		}
		url = build_url(url_params)
		listitem = make_listitem()
		listitem.setLabel(label)

		poster = _get_poster(ep, 'w342') or kodi_utils.get_icon('calender')
		still = _get_still(ep, 'w300')
		listitem.setArt({
			'icon': poster,
			'poster': poster,
			'thumb': still or poster,
			'fanart': fanart,
		})

		cm = []
		cm.append(('[B]Go to Show[/B]', 'Container.Update(%s)' % build_url({'mode': 'build_season_list', 'tmdb_id': tmdb_id})))
		cm.append(('[B]Go to Season[/B]', 'Container.Update(%s)' % build_url({'mode': 'build_episode_list', 'tmdb_id': tmdb_id, 'season': season_num})))
		listitem.addContextMenuItems(cm)

		info_tag = listitem.getVideoInfoTag(True)
		info_tag.setMediaType('episode')
		info_tag.setTvShowTitle(ep.get('show_title', ''))
		info_tag.setTitle(ep.get('episode_title', ''))
		info_tag.setSeason(ep.get('season_number', 0))
		info_tag.setEpisode(ep.get('episode_number', 0))
		info_tag.setPlot(plot)
		if ep.get('runtime'):
			info_tag.setDuration(ep['runtime'] * 60)
		try:
			s_e = (int(ep.get('season_number', 0)), int(ep.get('episode_number', 0)))
			if tmdb_id in watched_cache and s_e in watched_cache[tmdb_id]:
				info_tag.setPlaycount(1)
		except: pass

		items.append((url, listitem, False))

	add_items(handle, items)

	date_obj = datetime.strptime(target_date, '%Y-%m-%d')
	today = datetime.now().date()
	tomorrow = today + timedelta(days=1)
	if date_obj.date() == today:
		cat = 'Today'
	elif date_obj.date() == tomorrow:
		cat = 'Tomorrow'
	else:
		cat = date_obj.strftime('%A, %b %d')

	kodi_utils.set_content(handle, 'episodes')
	kodi_utils.set_category(handle, cat)
	kodi_utils.end_directory(handle, cacheToDisc=False)
	kodi_utils.set_view_mode('view.episodes_single', 'episodes')
