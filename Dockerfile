# BEGIN LICENSE HEADER
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 Scott Rogers <scott@scottandrewrogers.com>
#
# Part of rally-route-finder. Licensed under the Apache License, Version 2.0;
# see the LICENSE and NOTICE files in the repository root.
# Redistributions must retain this notice and the NOTICE file.
#
# Commit history (date time tz | author <email> | commit | message):
#   2026-11-02 10:04:06 -0500 | Scott Rogers <scott@scottandrewrogers.com> | 5a4db15 | Offer the beam search as a quick mode, in planRoute.py and the web app
#   2026-11-02 08:04:22 -0500 | Scott Rogers <scott@scottandrewrogers.com> | 9031e6c | Check a finished web route on real roads with Google, behind GOOGLE_CHECK
#   2026-11-01 13:46:31 -0500 | Scott Rogers <scott@scottandrewrogers.com> | ef8f9bf | Add a password-protected web app for running planner scenarios
# END LICENSE HEADER
# The web app (webapp/app.py) under PyPy, which runs the planner about 7x
# faster than regular Python
FROM pypy:3.11-7.3.20-slim

WORKDIR /app
COPY webapp/requirements.txt webapp/requirements.txt
RUN pip install --no-cache-dir -r webapp/requirements.txt
COPY planRoute.py planRouteSearch.py checkRoute.py ./
COPY webapp webapp

# The bonus files are mounted at /data; runs are saved in /results
ENV DATA_DIR=/data RESULTS_DIR=/results
EXPOSE 8000
# One process, so there's one queue of runs; threads serve pages while a run goes
CMD ["gunicorn", "--chdir", "webapp", "--workers", "1", "--threads", "8", "--bind", "0.0.0.0:8000", "app:app"]
