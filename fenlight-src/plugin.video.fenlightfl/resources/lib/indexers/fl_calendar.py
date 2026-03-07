# -*- coding: utf-8 -*-
# FL Calendar - shows upcoming episodes grouped by day

import sys
import json
import time
from datetime import datetime, timedelta
from modules import kodi_utils, settings, watched_status as ws
from apis.flicklist_api import call_flicklist
from caches.settings_cache import get_setting

TMDB_IMAGE_URL = 'https://image.tmdb.org/t/p/%s%s'

# ── API Fetch ────────────────────────────────────────────────────────────

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

# ── Helpers ──────────────────────────────────────────────────────────────

def _format_day_label(date_str, ep_count):
	"""Format: 'TODAY · 3 episodes' or 'Wed Feb 19 · 5 episodes' """
	date_obj = datetime(*(time.strptime(date_str, '%Y-%m-%d')[0:6]))
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


# ── Day-Folder View ─────────────────────────────────────────────────────
# Shows one folder per day with episode count in the label
# Empty days are skipped (progressive disclosure)

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

	# ── Auth check ──
	if not _is_authenticated():
		listitem = make_listitem()
		listitem.setLabel('[COLOR ff22d3a7]Log in to FlickList to see your calendar[/COLOR]')
		listitem.setArt({'icon': kodi_utils.get_icon('calender'), 'fanart': fanart})
		info_tag = listitem.getVideoInfoTag(True)
		info_tag.setPlot('Click here to authorize your FlickList account.\nThen add shows to your calendar on flicklist.tv')
		url = build_url({'mode': 'fl.fl_authenticate', 'isFolder': 'false'})
		add_items(handle, [(url, listitem, False)])
		kodi_utils.set_content(handle, '')
		kodi_utils.set_category(handle, 'FL Calendar')
		kodi_utils.end_directory(handle)
		return

	# ── 7-day sliding window ──
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

	# Filter to only our 7-day window
	calendar_days = [d for d in calendar_days if start_str <= d.get('date', '') <= end_str]

	items = []

	# ── Previous Week (cap at 12 weeks back) ──
	if offset > -84:
		prev_li = make_listitem()
		prev_li.setLabel('[COLOR ff22d3a7][B]<  Previous Week[/B][/COLOR]')
		prev_li.setArt({'icon': kodi_utils.get_icon('calender'), 'fanart': fanart})
		prev_li.getVideoInfoTag(True).setPlot('Show the previous 7 days')
		items.append((build_url({'mode': 'fl_calendar.build_calendar_days', 'offset': offset - 7}), prev_li, True))

	# ── Day folders ──
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

	# ── Empty state ──
	if day_count == 0:
		empty_li = make_listitem()
		empty_li.setLabel('[COLOR ff888888]No episodes this week[/COLOR]')
		empty_li.setArt({'icon': kodi_utils.get_icon('calender'), 'fanart': fanart})
		items.append((build_url({}), empty_li, False))

	# ── Next Week (cap at 4 weeks forward) ──
	if offset < 28:
		next_li = make_listitem()
		next_li.setLabel('[COLOR ff22d3a7][B]Next Week  >[/B][/COLOR]')
		next_li.setArt({'icon': kodi_utils.get_icon('calender'), 'fanart': fanart})
		next_li.getVideoInfoTag(True).setPlot('Show the next 7 days')
		items.append((build_url({'mode': 'fl_calendar.build_calendar_days', 'offset': offset + 7}), next_li, True))

	# ── Category header shows date range ──
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

	# Calculate how far back/forward we need to fetch based on the target date
	try:
		target_dt = datetime(*(time.strptime(target_date, '%Y-%m-%d')[0:6]))
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

	# ── Full metadata setup (same pattern as episodes.py) ──
	from modules.metadata import tvshow_meta, episodes_meta
	from modules.utils import get_datetime, adjust_premiered_date

	current_date = get_datetime()
	api_key = settings.tmdb_api_key()
	mpaa_region = settings.mpaa_region()
	watched_indicators = settings.watched_indicators()
	watched_db = ws.get_database(watched_indicators)
	playback_key = settings.playback_key()
	play_mode = 'playback.%s' % playback_key
	adjust_hours = settings.date_offset()
	no_spoilers = settings.avoid_episode_spoilers()
	poster_empty = kodi_utils.get_icon('box_office')
	fanart_empty = kodi_utils.addon_fanart()
	kodi_actor = kodi_utils.kodi_actor()
	is_external = kodi_utils.external()

	# Sort episodes: by show title, then season, then episode number
	sorted_episodes = sorted(day_data['items'], key=lambda x: (
		x.get('show_title', '').lower(),
		int(x.get('season_number', 0)),
		int(x.get('episode_number', 0))
	))

	# Cache tvshow_meta per tmdb_id (avoid re-fetching for multi-episode shows)
	meta_cache = {}

	for ep in sorted_episodes:
		try:
			tmdb_id = ep.get('tmdb_id', 0)
			season_num = int(ep.get('season_number', 1))
			episode_num = int(ep.get('episode_number', 1))
			if not tmdb_id: continue

			# ── Fetch full show metadata (cached) ──
			if tmdb_id not in meta_cache:
				meta_cache[tmdb_id] = tvshow_meta('tmdb_id', tmdb_id, api_key, mpaa_region, current_date)
			meta = meta_cache[tmdb_id]
			if not meta: continue
			meta_get = meta.get
			tvdb_id = meta_get('tvdb_id', 0)
			imdb_id = meta_get('imdb_id', '')
			title = meta_get('title', '')
			orig_title = meta_get('original_title', '')
			show_year = meta_get('year') or '2050'
			show_duration = meta_get('duration', 0)
			show_status = meta_get('status', '')
			mpaa = meta_get('mpaa', '')
			trailer = str(meta_get('trailer', ''))
			genre = meta_get('genre', [])
			studio = meta_get('studio', [])
			country = meta_get('country', [])
			cast = meta_get('short_cast', []) or meta_get('cast', []) or []
			tvshow_plot = meta_get('plot', '')
			show_poster = meta_get('poster') or poster_empty
			show_fanart = meta_get('fanart') or fanart_empty
			show_clearlogo = meta_get('clearlogo') or ''
			show_landscape = meta_get('landscape') or ''

			# Season poster
			season_poster = show_poster
			try:
				season_data = meta_get('season_data')
				poster_path = next((i['poster_path'] for i in season_data if i['season_number'] == season_num), None)
				if poster_path: season_poster = 'https://image.tmdb.org/t/p/w780%s' % poster_path
			except: pass

			# ── Fetch episode metadata ──
			ep_meta_list = episodes_meta(season_num, meta)
			item = None
			if ep_meta_list:
				item = next((i for i in ep_meta_list if i['episode'] == episode_num), None)

			if item:
				item_get = item.get
				ep_name = item_get('title', '')
				premiered = item_get('premiered', '')
				episode_type = item_get('episode_type') or ''
				episode_id = item_get('episode_id') or None
				duration = item_get('duration') or show_duration
				director = item_get('director', [])
				writer = item_get('writer', [])
				guest_stars = item_get('guest_stars', [])
				rating = item_get('rating', 0)
				votes = item_get('votes', 0)
			else:
				# Fallback to calendar API data if episodes_meta fails
				ep_name = ep.get('episode_title', '')
				premiered = ep.get('air_date', '')
				episode_type = ''
				episode_id = None
				duration = (ep.get('runtime') or 0) * 60
				director, writer, guest_stars = [], [], []
				rating, votes = 0, 0

			try: year = premiered.split('-')[0]
			except: year = show_year or '2050'

			# ── Watched status + progress ──
			watched_info = ws.watched_info_episode(str(tmdb_id), watched_db)
			playcount = ws.get_watched_status_episode(watched_info, (season_num, episode_num))
			bookmarks = ws.get_bookmarks_episode(tmdb_id, season_num, watched_db)
			progress = ws.get_progress_status_episode(bookmarks, episode_num)

			# Spoiler protection
			if no_spoilers and not playcount:
				thumb = show_landscape or show_fanart
				plot = tvshow_plot or '* Hidden to Prevent Spoilers *'
			else:
				if item:
					thumb = item_get('thumb', None) or show_landscape or show_fanart
					plot = item_get('plot') or tvshow_plot
				else:
					thumb = _get_still(ep, 'w300') or show_landscape or show_fanart
					plot = ep.get('overview', '') or tvshow_plot

			# ── Label ──
			label = _format_episode_label(ep)

			# ── URLs (matching episodes.py) ──
			play_params = build_url({'mode': play_mode, 'media_type': 'episode', 'tmdb_id': tmdb_id, 'season': season_num, 'episode': episode_num,
									'playcount': playcount, 'episode_id': episode_id, playback_key: playback_key})
			extras_params = build_url({'mode': 'extras_menu_choice', 'tmdb_id': tmdb_id, 'media_type': 'episode', 'is_external': is_external})
			options_params = build_url({'mode': 'options_menu_choice', 'content': 'episode', 'tmdb_id': tmdb_id, 'poster': show_poster, 'is_external': is_external})
			playback_options_params = build_url({'mode': 'playback_choice', 'media_type': 'episode', 'meta': tmdb_id, 'season': season_num,
												'playcount': playcount, 'episode': episode_num, 'episode_id': episode_id})

			# ── Context menu (same as episodes.py) ──
			cm = []
			cm.append(('[B]Extras[/B]', 'RunPlugin(%s)' % extras_params))
			cm.append(('[B]Options[/B]', 'RunPlugin(%s)' % options_params))
			cm.append(('[B]Play Options[/B]', 'RunPlugin(%s)' % playback_options_params))
			if playcount:
				cm.append(('[B]Mark Unwatched[/B]', 'RunPlugin(%s)' % build_url({'mode': 'watched_status.mark_episode', 'action': 'mark_as_unwatched',
							'tmdb_id': tmdb_id, 'tvdb_id': tvdb_id, 'season': season_num, 'episode': episode_num, 'title': title})))
			else:
				cm.append(('[B]Mark Watched[/B]', 'RunPlugin(%s)' % build_url({'mode': 'watched_status.mark_episode', 'action': 'mark_as_watched',
							'tmdb_id': tmdb_id, 'tvdb_id': tvdb_id, 'season': season_num, 'episode': episode_num, 'title': title})))
			if progress:
				cm.append(('[B]Clear Progress[/B]', 'RunPlugin(%s)' % build_url({'mode': 'watched_status.erase_bookmark', 'media_type': 'episode',
							'tmdb_id': tmdb_id, 'season': season_num, 'episode': episode_num, 'refresh': 'true'})))
			cm.append(('[B]Browse Seasons[/B]', 'Container.Update(%s)' % build_url({'mode': 'build_season_list', 'tmdb_id': tmdb_id})))
			cm.append(('[B]Browse Episodes[/B]', 'Container.Update(%s)' % build_url({'mode': 'build_episode_list', 'tmdb_id': tmdb_id, 'season': season_num})))

			# ── Build listitem ──
			listitem = make_listitem()
			listitem.setLabel(label)
			listitem.addContextMenuItems(cm)
			listitem.setArt({'poster': show_poster, 'fanart': show_fanart, 'thumb': thumb, 'icon': thumb,
							'clearlogo': show_clearlogo, 'landscape': show_landscape,
							'season.poster': season_poster, 'tvshow.poster': show_poster, 'tvshow.clearlogo': show_clearlogo})
			set_properties = listitem.setProperties
			set_properties({'episode_type': episode_type, 'fenlightfl.extras_params': extras_params,
							'fenlightfl.options_params': options_params, 'fenlightfl.playback_options_params': playback_options_params})

			# ── Info tag (full, matching episodes.py) ──
			info_tag = listitem.getVideoInfoTag(True)
			info_tag.setMediaType('episode')
			info_tag.setTitle(ep_name)
			info_tag.setOriginalTitle(orig_title)
			info_tag.setTvShowTitle(title)
			info_tag.setGenres(genre)
			info_tag.setPlaycount(playcount)
			info_tag.setSeason(season_num)
			info_tag.setEpisode(episode_num)
			info_tag.setPlot(plot)
			info_tag.setDuration(duration)
			info_tag.setIMDBNumber(imdb_id)
			info_tag.setUniqueIDs({'imdb': imdb_id, 'tmdb': str(tmdb_id), 'tvdb': str(tvdb_id)})
			info_tag.setFirstAired(premiered)
			info_tag.setTvShowStatus(show_status)
			info_tag.setCountries(country)
			info_tag.setTrailer(trailer)
			info_tag.setDirectors(director)
			info_tag.setYear(int(year))
			info_tag.setRating(rating)
			info_tag.setVotes(votes)
			info_tag.setMpaa(mpaa)
			info_tag.setStudios(studio)
			info_tag.setWriters(writer)
			full_cast = cast + guest_stars
			info_tag.setCast([kodi_actor(name=i['name'], role=i['role'], thumbnail=i['thumbnail']) for i in full_cast])
			if progress:
				info_tag.setResumePoint(ws.get_resume_seconds(progress, duration))
				set_properties({'WatchedProgress': progress})

			items.append((play_params, listitem, False))
		except: pass

	add_items(handle, items)

	# Format the category header
	date_obj = datetime(*(time.strptime(target_date, '%Y-%m-%d')[0:6]))
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
