
import sys
from datetime import datetime, timedelta
from modules import kodi_utils


MOCK_CALENDAR = [
	{
		'date': '2026-02-17',
		'items': [
			{'show_title': 'Jujutsu Kaisen', 'season': 3, 'episode': 5, 'episode_title': 'Hidden Inventory',
			 'tmdb_id': 95479, 'air_time': '10:00 AM', 'network': 'Crunchyroll'},
			{'show_title': 'Solo Leveling', 'season': 2, 'episode': 8, 'episode_title': 'Arise',
			 'tmdb_id': 209867, 'air_time': '11:30 PM', 'network': 'Crunchyroll'},
			{'show_title': 'One Piece', 'season': 2, 'episode': 1087, 'episode_title': 'The Last Island',
			 'tmdb_id': 37854, 'air_time': '7:00 PM', 'network': 'Crunchyroll'},
		]
	},
	{
		'date': '2026-02-18',
		'items': [
			{'show_title': 'Severance', 'season': 2, 'episode': 7, 'episode_title': 'Chroma Theory',
			 'tmdb_id': 95396, 'air_time': '12:00 AM', 'network': 'Apple TV+'},
			{'show_title': 'Reacher', 'season': 3, 'episode': 4, 'episode_title': 'The Hard Way',
			 'tmdb_id': 108978, 'air_time': '3:00 AM', 'network': 'Prime Video'},
		]
	},
	{
		'date': '2026-02-19',
		'items': [
			{'show_title': 'Demon Slayer', 'season': 5, 'episode': 3, 'episode_title': 'Infinity Castle',
			 'tmdb_id': 85937, 'air_time': '10:45 AM', 'network': 'Crunchyroll'},
			{'show_title': 'The White Lotus', 'season': 3, 'episode': 1, 'episode_title': 'Aloha',
			 'tmdb_id': 110316, 'air_time': '9:00 PM', 'network': 'Max'},
			{'show_title': 'Dragon Ball Daima', 'season': 1, 'episode': 20, 'episode_title': 'Warrior',
			 'tmdb_id': 246480, 'air_time': '9:30 AM', 'network': 'Crunchyroll'},
			{'show_title': 'Dandadan', 'season': 1, 'episode': 18, 'episode_title': 'Turbo Granny Returns',
			 'tmdb_id': 226073, 'air_time': '11:00 AM', 'network': 'Crunchyroll'},
			{'show_title': 'Abbott Elementary', 'season': 4, 'episode': 12, 'episode_title': 'Teacher Prep',
			 'tmdb_id': 131927, 'air_time': '9:00 PM', 'network': 'ABC'},
		]
	},
	{
		'date': '2026-02-20',
		'items': [
			{'show_title': 'Sakamoto Days', 'season': 1, 'episode': 8, 'episode_title': 'Assassin Exam',
			 'tmdb_id': 241070, 'air_time': '10:00 AM', 'network': 'Netflix'},
		]
	},
	{
		'date': '2026-02-21',
		'items': [
			{'show_title': 'Invincible', 'season': 3, 'episode': 5, 'episode_title': 'Guardians',
			 'tmdb_id': 95557, 'air_time': '3:00 AM', 'network': 'Prime Video'},
			{'show_title': 'My Hero Academia', 'season': 8, 'episode': 3, 'episode_title': 'Plus Ultra',
			 'tmdb_id': 65930, 'air_time': '5:30 AM', 'network': 'Crunchyroll'},
			{'show_title': 'Chainsaw Man', 'season': 2, 'episode': 1, 'episode_title': 'Reze Arc',
			 'tmdb_id': 114410, 'air_time': '12:00 PM', 'network': 'Crunchyroll'},
			{'show_title': 'The Last of Us', 'season': 2, 'episode': 5, 'episode_title': 'Rattlers',
			 'tmdb_id': 100088, 'air_time': '9:00 PM', 'network': 'Max'},
		]
	},
	{
		'date': '2026-02-22',
		'items': []
	},
	{
		'date': '2026-02-23',
		'items': [
			{'show_title': 'Bleach: TYBW', 'season': 3, 'episode': 10, 'episode_title': 'The Blade Is Me',
			 'tmdb_id': 31580, 'air_time': '8:30 AM', 'network': 'Hulu'},
			{'show_title': 'Yellowjackets', 'season': 3, 'episode': 2, 'episode_title': 'Old Wounds',
			 'tmdb_id': 125988, 'air_time': '9:00 PM', 'network': 'Paramount+'},
		]
	},
]


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
	"""Format: 'Jujutsu Kaisen · S3E5 · Hidden Inventory · 10:00 AM' """
	s_num = str(item['season']).zfill(2)
	e_num = str(item['episode']).zfill(2)
	parts = [
		'[B]%s[/B]' % item['show_title'],
		'S%sE%s' % (s_num, e_num),
	]
	if item.get('episode_title'):
		parts.append(item['episode_title'])
	if item.get('air_time'):
		parts.append('[COLOR ff888888]%s[/COLOR]' % item['air_time'])
	return '  ·  '.join(parts)


def _format_episode_plot(item):
	"""Plot shown in info panel"""
	s_num = str(item['season']).zfill(2)
	e_num = str(item['episode']).zfill(2)
	lines = [
		'[B]%s[/B]' % item['show_title'],
		'Season %s, Episode %s' % (s_num, e_num),
	]
	if item.get('episode_title'):
		lines.append(item['episode_title'])
	if item.get('network'):
		lines.append('')
		lines.append('[COLOR ff22d3a7]%s[/COLOR]' % item['network'])
	if item.get('air_time'):
		lines.append(item['air_time'])
	return '\n'.join(lines)


def build_calendar_days(params):
	"""Root calendar view: one folder per day, click to see episodes."""
	handle = int(sys.argv[1])
	build_url = kodi_utils.build_url
	make_listitem = kodi_utils.make_listitem
	add_items = kodi_utils.add_items
	fanart = kodi_utils.get_addon_fanart()
	is_anime = 'is_anime_list' in params

	items = []
	for day in MOCK_CALENDAR:
		ep_count = len(day['items'])
		if ep_count == 0:
			continue

		date_str = day['date']
		label = _format_day_label(date_str, ep_count)

		preview_shows = [i['show_title'] for i in day['items'][:5]]
		plot = '\n'.join(preview_shows)
		if ep_count > 5:
			plot += '\n+ %d more...' % (ep_count - 5)

		url_params = {
			'mode': 'fl_calendar.build_calendar_day',
			'date': date_str,
		}
		if is_anime:
			url_params['is_anime_list'] = 'true'

		url = build_url(url_params)
		listitem = make_listitem()
		listitem.setLabel(label)

		icon = kodi_utils.get_icon('calender')
		listitem.setArt({'icon': icon, 'poster': icon, 'thumb': icon, 'fanart': fanart, 'banner': icon})
		info_tag = listitem.getVideoInfoTag(True)
		info_tag.setPlot(plot)

		items.append((url, listitem, True))

	add_items(handle, items)
	kodi_utils.set_content(handle, '')
	kodi_utils.set_category(handle, 'FL Calendar' if not is_anime else 'Anime Calendar')
	kodi_utils.end_directory(handle)
	kodi_utils.set_view_mode('view.main', '')


def build_calendar_day(params):
	"""Episode list for a specific day."""
	handle = int(sys.argv[1])
	build_url = kodi_utils.build_url
	make_listitem = kodi_utils.make_listitem
	add_items = kodi_utils.add_items
	fanart = kodi_utils.get_addon_fanart()

	target_date = params.get('date', '')

	day_data = None
	for day in MOCK_CALENDAR:
		if day['date'] == target_date:
			day_data = day
			break

	if not day_data or not day_data['items']:
		kodi_utils.end_directory(handle)
		return

	items = []
	for ep in day_data['items']:
		label = _format_episode_label(ep)
		plot = _format_episode_plot(ep)

		url_params = {
			'mode': 'build_season_list',
			'tmdb_id': ep['tmdb_id'],
		}
		url = build_url(url_params)
		listitem = make_listitem()
		listitem.setLabel(label)

		icon = kodi_utils.get_icon('calender')
		listitem.setArt({'icon': icon, 'poster': icon, 'thumb': icon, 'fanart': fanart})

		info_tag = listitem.getVideoInfoTag(True)
		info_tag.setMediaType('episode')
		info_tag.setTvShowTitle(ep['show_title'])
		info_tag.setTitle(ep.get('episode_title', ''))
		info_tag.setSeason(ep['season'])
		info_tag.setEpisode(ep['episode'])
		info_tag.setPlot(plot)

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
