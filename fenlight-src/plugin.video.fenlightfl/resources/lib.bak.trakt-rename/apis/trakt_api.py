# -*- coding: utf-8 -*-
# Shim: the dynamic import in movies.py / tvshows.py resolves trakt_* actions
# to 'apis.trakt_api'. All functions live in flicklist_api.py.
from apis.flicklist_api import *
