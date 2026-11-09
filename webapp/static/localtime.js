// BEGIN LICENSE HEADER
// SPDX-License-Identifier: Apache-2.0
// Copyright 2025-2026 Scott Rogers <scott@scottandrewrogers.com>
//
// Part of rally-route-finder. Licensed under the Apache License, Version 2.0;
// see the LICENSE and NOTICE files in the repository root.
// Redistributions must retain this notice and the NOTICE file.
//
// Commit history (date time tz | author <email> | commit | message):
//   2026-11-03 12:10:24 -0500 | Scott Rogers <scott@scottandrewrogers.com> | edb0c2c | Web app: local times, and a layout that fits laptop screens
// END LICENSE HEADER
// Show each <time datetime="..."> in the viewer's own time zone, e.g.
// "Nov 3, 8:45 AM"; without JavaScript it keeps the UTC text the server wrote.
document.querySelectorAll('time[datetime]').forEach(el => {
  const when = new Date(el.getAttribute('datetime'));
  if (Number.isNaN(when.getTime())) return;
  el.textContent = when.toLocaleString(undefined, {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'});
  el.title = when.toLocaleString(undefined, {dateStyle: 'full', timeStyle: 'long'});
});
