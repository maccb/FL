# -*- coding: utf-8 -*-
# Shim: the dynamic import in movies.py / tvshows.py resolves fl_* actions
# to 'apis.fl_api'. All functions live in flicklist_api.py.
from apis.flicklist_api import *
