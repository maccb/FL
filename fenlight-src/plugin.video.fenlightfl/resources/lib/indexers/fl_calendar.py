
import sys
import json
from datetime import datetime, timedelta
from modules import kodi_utils
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
	"""Root calendar view: one folder per day, click to see episodes.
	Fetches from GET /api/calendar/my/shows/{start}/{days}."""
	handle = int(sys.argv[1])
	build_url = kodi_utils.build_url
	make_listitem = kodi_utils.make_listitem
	add_items = kodi_utils.add_items
	fanart = kodi_utils.get_addon_fanart()

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

	calendar_days = _fetch_calendar(previous_days=7, future_days=14)
	if calendar_days is None:
		listitem = make_listitem()
		listitem.setLabel('[COLOR ffff4444]Could not load calendar — check connection[/COLOR]')
		listitem.setArt({'icon': kodi_utils.get_icon('calender'), 'fanart': fanart})
		add_items(handle, [(build_url({}), listitem, False)])
		kodi_utils.set_content(handle, '')
		kodi_utils.set_category(handle, 'FL Calendar')
		kodi_utils.end_directory(handle)
		return

	items = []
	for day in calendar_days:
		day_items = day.get('items', [])
		ep_count = len(day_items)
		if ep_count == 0:
			continue

		date_str = day['date']
		label = _format_day_label(date_str, ep_count)

		show_names = list(dict.fromkeys(i.get('show_title', '') for i in day_items))
		plot = '\n'.join(show_names[:5])
		if len(show_names) > 5:
			plot += '\n+ %d more...' % (len(show_names) - 5)

		url_params = {
			'mode': 'fl_calendar.build_calendar_day',
			'date': date_str,
		}

		url = build_url(url_params)
		listitem = make_listitem()
		listitem.setLabel(label)

		first_poster = None
		for di in day_items:
			first_poster = _get_poster(di)
			if first_poster:
				break
		icon = first_poster or kodi_utils.get_icon('calender')
		listitem.setArt({'icon': icon, 'poster': icon, 'thumb': icon, 'fanart': fanart, 'banner': icon})
		info_tag = listitem.getVideoInfoTag(True)
		info_tag.setPlot(plot)

		items.append((url, listitem, True))

	if not items:
		listitem = make_listitem()
		listitem.setLabel('[COLOR ff888888]No upcoming episodes — add shows on flicklist.tv[/COLOR]')
		listitem.setArt({'icon': kodi_utils.get_icon('calender'), 'fanart': fanart})
		info_tag = listitem.getVideoInfoTag(True)
		info_tag.setPlot('Add shows to your watchlist or tracked list on flicklist.tv\nand their upcoming episodes will appear here.')
		items.append((build_url({}), listitem, False))

	add_items(handle, items)
	kodi_utils.set_content(handle, '')
	kodi_utils.set_category(handle, 'FL Calendar')
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

	calendar_days = _fetch_calendar(previous_days=7, future_days=14)
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
	for ep in day_data['items']:
		label = _format_episode_label(ep)
		plot = _format_episode_plot(ep)

		url_params = {
			'mode': 'build_season_list',
			'tmdb_id': ep.get('tmdb_id', 0),
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

		info_tag = listitem.getVideoInfoTag(True)
		info_tag.setMediaType('episode')
		info_tag.setTvShowTitle(ep.get('show_title', ''))
		info_tag.setTitle(ep.get('episode_title', ''))
		info_tag.setSeason(ep.get('season_number', 0))
		info_tag.setEpisode(ep.get('episode_number', 0))
		info_tag.setPlot(plot)
		if ep.get('runtime'):
			info_tag.setDuration(ep['runtime'] * 60)

		items.append((url, listitem, True))

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
