"""Profile and connection views. Bounded pages, offline scatter plot and existing evidence drilldown."""
from __future__ import annotations

import customtkinter as ctk


def evidence_details(record):
    """The values behind new inferences, with an explicit bound on each displayed value."""
    meta = record.get('meta') or {}
    details = []
    for key, label in (('person', 'Person / creator'), ('action', 'Action'), ('caption', 'Caption'),
                       ('topic', 'Topic'), ('feedback', 'Feedback'), ('device', 'Device'), ('domain', 'Company / domain'),
                       ('advertiser', 'Advertiser label')):
        value = meta.get(key)
        if value is None or value == '':
            continue
        text = str(value)
        if len(text) > 4000:
            text = text[:4000] + f'… [preview; {len(text)} characters in source record]'
        details.append(f'{label}: {text}')
    if meta.get('lat') is not None and meta.get('lon') is not None:
        details.append(f"Recorded coordinates: {meta['lat']}, {meta['lon']}")
    if meta.get('fields'):
        details.append('Information fields: ' + ', '.join(str(k) for k in meta['fields']))
    if meta.get('source') == 'local_photo':
        for key, value in (meta.get('metadata') or {}).items():
            details.append(f'Photo {key}: {str(value)[:500]}')
        details.append('SHA-256: ' + str(meta.get('sha256', '')))
        details.append('Perceptual hash: ' + str(meta.get('phash', '')))
        details.append('OCR pattern flags: ' + (', '.join(meta.get('sensitive_text') or []) or 'none detected / OCR unavailable'))
    return details


def evidence_button(app, parent, value, text='Evidence'):
    return ctk.CTkButton(parent, text=text, width=110,
                         command=lambda: app.show_evidence({'title': value.get('label') or value.get('name', ''),
                                                            'evidence': value.get('evidence', [])}))


def paged_items(parent, values, render, size=20):
    controls = ctk.CTkFrame(parent, fg_color='transparent')
    controls.pack(fill='x', padx=8, pady=5)
    body = ctk.CTkFrame(parent, fg_color='transparent')
    body.pack(fill='x')
    current = [0]

    def show(index):
        current[0] = index
        for child in body.winfo_children():
            child.destroy()
        for value in values[index * size:(index + 1) * size]:
            render(body, value)
        count.configure(text=f'{len(values)} items | Page {index + 1} of {max(1, (len(values) + size - 1) // size)}')
        previous.configure(state='normal' if index else 'disabled')
        following.configure(state='normal' if (index + 1) * size < len(values) else 'disabled')

    previous = ctk.CTkButton(controls, text='Prev', width=65, command=lambda: show(current[0] - 1))
    previous.pack(side='left')
    count = ctk.CTkLabel(controls, text='')
    count.pack(side='left', expand=True)
    following = ctk.CTkButton(controls, text='Next', width=65, command=lambda: show(current[0] + 1))
    following.pack(side='right')
    show(0)


def inference_card(app, parent, value):
    card = app.card(parent)
    app.label(card, value['label'], bold=True)
    app.label(card, f"{value.get('source', 'NexData-inferred')} | confidence {value.get('confidence', 0):.0%} (heuristic)", size=12)
    if value.get('warning'):
        app.label(card, value['warning'], color='#ffb975')
    if value.get('note'):
        app.label(card, value['note'], size=12)
    evidence_button(app, card, value).pack(anchor='w', padx=16, pady=8)


def render_profile(app):
    page = app.scroll_page('Profile')
    profile = app.result.get('profile') or {}
    app.label(page, profile.get('title', 'Your profile as the algorithms see it'), bold=True, size=20)
    app.label(page, profile.get('notice', 'Import account exports to build an evidence-backed profile.'))
    for key, title in (('interests', 'Hobbies & interests'), ('likes', 'Creators, brands & content types'),
                       ('dislikes', 'Less of this content'), ('shopping', 'Shopping profile'),
                       ('life_stage', 'Life-stage guesses'), ('sensitive', 'Sensitive inferences — review separately')):
        app.label(page, title, bold=True, size=18)
        values = profile.get(key) or []
        if values:
            paged_items(page, values, lambda parent, value: inference_card(app, parent, value))
        else:
            app.label(page, 'No supported evidence in these imports.', size=12)
    routine = profile.get('routine') or {}
    app.label(page, 'Daily routine', bold=True, size=18)
    if routine.get('evidence'):
        inference_card(app, page, routine)
        app.label(page, 'Peak timestamped-record hours: ' + ', '.join(f'{h:02}:00' for h in routine.get('peak_hours', [])))
        app.label(page, routine.get('timezone_note', ''), size=12)
        app.label(page, f"Weekdays: {sum(routine.get('weekday_hours', []))} timestamped records across {routine.get('weekday_observed_days', 0)} observed days; "
                        f"weekends: {sum(routine.get('weekend_hours', []))} across {routine.get('weekend_observed_days', 0)} observed days.")
        if routine.get('sleep_window'):
            inference_card(app, page, routine['sleep_window'])
    else:
        app.label(page, 'Insufficient timestamped activity to infer a routine.')
    app.label(page, 'Illustrative ad-targeting preview', bold=True, size=18)
    app.label(page, 'Possible categories suggested by exported evidence. Availability and actual targeting are unverified; sensitive affinities are excluded.')
    paged_items(page, (app.result.get('extras') or {}).get('ad_targeting', []),
                lambda parent, value: inference_card(app, parent, value))


def plot_places(ax, places):
    """Unique coordinate reference points. The map contains no online tiles or basemap."""
    points = {}
    for place in places:
        if place.get('lat') is not None and place.get('lon') is not None:
            if place['id'] not in points:
                points[place['id']] = dict(place, evidence=[])
            entry = points[place['id']]
            entry['evidence'].extend(place.get('evidence') or [])
    values = list(points.values())
    if values:
        dots = ax.scatter([v['lon'] for v in values], [v['lat'] for v in values], color='#56d9ed', alpha=0.8, picker=6)
        for value in values[:20]:
            ax.annotate(value['name'], (value['lon'], value['lat']), xytext=(4, 4), textcoords='offset points', color='#ecf2fa', fontsize=8)
    else:
        dots = None
        ax.text(0.5, 0.5, 'No supported place evidence', ha='center', transform=ax.transAxes, color='#a4b2c5')
    ax.set(xlabel='Longitude (approximate reference)', ylabel='Latitude (approximate reference)')
    ax.xaxis.label.set_color('#a4b2c5')
    ax.yaxis.label.set_color('#a4b2c5')
    ax.grid(alpha=0.15)
    return dots, values


def render_connections(app):
    page = app.scroll_page('Connections & places')
    app.label(page, 'Connections & places', bold=True, size=20)
    app.label(page, 'Inferred from exported interactions. A score is activity, not friendship quality. Place mentions and shared mentions do not prove a visit or co-location.')
    places = app.result.get('places') or []
    fig, ax = app.new_figure(3.8)
    dots, values = plot_places(ax, places)
    fig.tight_layout()

    def picked(event):
        if event.artist is dots and len(event.ind):
            value = values[int(event.ind[0])]
            app.show_evidence({'title': value['name'], 'evidence': list(dict.fromkeys(value['evidence']))})

    app.mount_chart(page, fig)
    # mount_chart creates the Tk canvas; connect there because it replaces FigureCanvasBase.
    if app.canvases:
        app.canvases[-1].mpl_connect('pick_event', picked)
    app.label(page, f'{len(values)} place references. Click a point for source evidence. Coordinates are approximate and map coverage is limited.', size=12)

    def connection(parent, value):
        card = app.card(parent)
        app.label(card, f"{value['name']} | {value['platform']} | score {value['score']}", bold=True)
        app.label(card, 'Inferred: ' + value['relationship'])
        for label in value['labels']:
            app.label(card, label)
        app.label(card, ', '.join(f'{key}: {count}' for key, count in value['counts'].items()), size=12)
        evidence_button(app, card, value, 'All interactions').pack(anchor='w', padx=16, pady=5)
        ctk.CTkButton(card, text='Places & shared mentions', width=210,
                      command=lambda v=value: connection_details(app, v)).pack(anchor='w', padx=16, pady=8)

    paged_items(page, app.result.get('connections') or [], connection)
    app.label(page, 'Your place evidence and viewed-content mentions', bold=True, size=18)
    paged_items(page, places, lambda parent, value: inference_card(
        app, parent, dict(value, label=f"{value['name']} | {value['association']} | {value.get('timestamp') or 'date unavailable'}")))


def connection_details(app, value):
    popup = ctk.CTkToplevel(app)
    popup.title('Inferred places from exported content')
    popup.geometry('850x650')
    body = ctk.CTkScrollableFrame(popup)
    body.pack(fill='both', expand=True)
    app.label(body, value['name'], bold=True, size=20)
    app.label(body, 'Mentions in content you viewed; visits and co-location are unconfirmed.')
    def place_card(parent, row):
        if 'your_date' in row:
            label = f"{row['label']} | you: {row['your_date']} | them: {row['their_date']}"
        else:
            label = f"{row['name']} | {row.get('timestamp') or 'date unavailable'} | inferred mention"
        inference_card(app, parent, dict(row, label=label))

    paged_items(body, value['places'] + value['shared_places'], place_card)
    return popup


def render_extras(app, page):
    extras = app.result.get('extras') or {}
    app.label(page, 'Data age — oldest exported record', bold=True, size=18)
    for value in extras.get('data_age') or []:
        inference_card(app, page, value)
    app.label(page, 'Account-deletion directory', bold=True, size=18)
    app.label(page, extras.get('directory_note', 'Offline reference; routes may change.'))

    def deletion(parent, value):
        card = app.card(parent)
        app.label(card, value['service'] + ' | ' + value['status'], bold=True)
        if value.get('url'):
            app.action_link(card, value['url'])
        else:
            app.label(card, 'Unknown official deletion route. Check the service’s account/privacy settings.')
        if value.get('evidence'):
            evidence_button(app, card, value).pack(anchor='w', padx=16, pady=6)

    # Observed accounts first; the complete directory remains available on the following pages.
    observed = extras.get('deletion') or []
    seen = {v['service'] for v in observed}
    paged_items(page, observed + [v for v in extras.get('directory', []) if v['service'] not in seen], deletion)


def report_sections(result, line, pdf):
    def rows(values, limit=40):
        if len(values) > limit:
            line(f'Showing {limit} of {len(values)} items; the desktop view has paged access to every item.', 9)
        return values[:limit]

    def evidence(value):
        ids = value.get('evidence') or []
        line(f'Evidence: {len(ids)} records; ID preview: ' + ', '.join(ids[:20]), 9)

    profile = result.get('profile') or {}
    line('Your profile as the algorithms see it', 14, True)
    line(profile.get('notice', 'No profile evidence imported.'))
    for key, title in (('interests', 'Hobbies and interests'), ('likes', 'Likes'), ('dislikes', 'Dislikes'),
                       ('shopping', 'Shopping'), ('life_stage', 'Life-stage guesses'), ('sensitive', 'Sensitive inferences (separate)')):
        line(title, 12, True)
        for value in rows(profile.get(key) or []):
            line(f"{value['label']} | {value['source']} | confidence {value['confidence']:.0%} (heuristic)")
            if value.get('warning'):
                line(value['warning'])
            evidence(value)
    routine = profile.get('routine') or {}
    line('Daily routine', 12, True)
    line(routine.get('label', 'Insufficient timestamped-record evidence.'))
    if routine.get('evidence'):
        line(f"{routine['source']} | confidence {routine['confidence']:.0%} (heuristic)")
        evidence(routine)
    else:
        line('Insufficient timestamped-record evidence for a routine.')
    line(routine.get('timezone_note', ''))
    line('Peak timestamped-record hours: ' + ', '.join(f'{h:02}:00' for h in routine.get('peak_hours', [])))
    line(f"Weekday timestamped records: {sum(routine.get('weekday_hours', []))} across {routine.get('weekday_observed_days', 0)} observed days; "
         f"weekend timestamped records: {sum(routine.get('weekend_hours', []))} across {routine.get('weekend_observed_days', 0)} observed days.")
    if routine.get('sleep_window'):
        sleep = routine['sleep_window']
        line(sleep['label'])
        line(f"{sleep['source']} | confidence {sleep['confidence']:.0%} (heuristic)")
        evidence(sleep)
    line('Connections and places (inferred)', 14, True)
    line('Scores describe exported interactions. Mentions do not prove visits or co-location; reference coordinates are approximate.')
    for connection in rows(result.get('connections') or []):
        line(f"{connection['name']} | {connection['platform']} | score {connection['score']} | {connection['relationship']}")
        line(f"{connection['source']} | confidence {connection['confidence']:.0%} (heuristic)")
        for label in connection['labels']:
            line(label)
        evidence(connection)
        for place in rows(connection['places'], 10):
            line(f"Content mention: {place['name']} | {place.get('timestamp') or 'date unavailable'} | visit unconfirmed")
            evidence(place)
        for value in rows(connection['shared_places'], 10):
            line(f"{value['label']} | {value['your_date']} / {value['their_date']}")
            evidence(value)
    for place in rows(result.get('places') or []):
        line(f"{place['name']} | {place['association']} | {place.get('timestamp') or 'date unavailable'} | {place['source']} | confidence {place['confidence']:.0%} (heuristic)")
        evidence(place)
    if result.get('places'):
        from matplotlib.figure import Figure
        from io import BytesIO
        fig = Figure(figsize=(9, 4), facecolor='#1b2432')
        ax = fig.add_subplot(111, facecolor='#1b2432')
        plot_places(ax, result['places'])
        fig.tight_layout()
        image = BytesIO()
        fig.savefig(image, format='png', dpi=120)
        image.seek(0)
        pdf.image(image, w=pdf.epw)
    extras = result.get('extras') or {}
    for key, title in (('data_age', 'Data age'), ('deletion', 'Deletion routes for observed services'), ('ad_targeting', 'Illustrative ad-targeting preview')):
        line(title, 14, True)
        for value in rows(extras.get(key) or []):
            line(value['label'])
            line(f"{value['source']} | confidence {value['confidence']:.0%} (heuristic)")
            if key == 'deletion':
                line(value.get('url') or 'Official deletion route unknown.')
            if value.get('note'):
                line(value['note'])
            evidence(value)
