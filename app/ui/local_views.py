"""Optional AI and retained-photo controls, using the desktop's existing evidence UI."""
from __future__ import annotations

import threading
from tkinter import filedialog

import customtkinter as ctk

from app.behavioral_intelligence.ai.config import AIConfigStore
from app.behavioral_intelligence.ai.models import AIConfig, LAN_WARNING
from app.behavioral_intelligence.ai.colibri_provider import ColibriProvider
from app.behavioral_intelligence.service import analyze_behavior
from app.cancellation import Cancelled, cancellation
from app.image_exposure.service import ImageExposureStore, scan_exposure, merge_photo_result
from .profile_views import paged_items


class LocalAnalysis:
    def __init__(self, app, root):
        self.app = app
        self.store = AIConfigStore(root)
        self.config = self.store.load()
        self.images = ImageExposureStore(root)
        self.ai_busy = False
        self.ai_result = None
        self.ai_view = -1

    def render_interests(self):
        app = self.app
        page = app.scroll_page('Interests (AI optional)')
        app.label(page, 'Interests from your exported evidence', bold=True, size=20)
        app.label(page, 'Local keyword and domain classification. Scores reflect unique evidence, platform diversity and recency; they are heuristic, not probabilities.')
        analysis = app.result.get('behavioral') or analyze_behavior(app.result.get('records', []))
        for note in analysis['profile']['analysisLimitations']:
            app.label(page, note, size=12)

        def interest(parent, row):
            card = app.card(parent)
            app.label(card, ' / '.join(row['primaryCategories']) + ' → ' + row['category'], bold=True)
            app.label(card, f"{row['level']} | score {row['score']} | {row['evidenceCount']} records | {row['sourceDiversity']} platforms | recency ×{row['recencyWeight']}", size=12)
            app.label(card, 'Topics: ' + ', '.join(row['topics']), size=12)
            app.label(card, row['explanation'], size=12)
            ctk.CTkButton(card, text='Evidence', command=lambda: app.show_evidence({'title': row['category'], 'evidence': row['evidence']})).pack(anchor='w', padx=16, pady=8)

        paged_items(page, analysis['interests'], interest)
        settings = app.card(page)
        app.label(settings, 'Optional model interpretation', bold=True, size=17)
        app.label(settings, 'Disabled by default. Only compact taxonomy aggregates and temporary evidence aliases are sent. Raw records, messages, cookies, names and paths stay local.', size=12)
        self.enabled = ctk.BooleanVar(value=self.config.enabled)
        self.lan = ctk.BooleanVar(value=self.config.allow_lan_model)
        ctk.CTkCheckBox(settings, text='Enable optional model', variable=self.enabled).pack(anchor='w', padx=16, pady=6)
        app.label(settings, 'Model endpoint (loopback by default)', size=12)
        self.endpoint = ctk.CTkEntry(settings, width=430)
        self.endpoint.insert(0, self.config.base_url)
        self.endpoint.pack(fill='x', padx=16, pady=4)
        app.label(settings, 'Model name (blank: use the first listed model)', size=12)
        self.model = ctk.CTkEntry(settings, width=430)
        self.model.insert(0, self.config.model)
        self.model.pack(fill='x', padx=16, pady=4)
        ctk.CTkCheckBox(settings, text='Allow a model on a private LAN device', variable=self.lan,
                        command=self._lan_warning).pack(anchor='w', padx=16, pady=8)
        self.warning = app.label(settings, '', color='#ffb975', size=12)
        self._lan_warning()
        self.ai_buttons = []
        for text, action in (('Save model settings', self.save_config), ('Check connection', lambda: self.run_ai(False)),
                             ('Generate local AI analysis', lambda: self.run_ai(True))):
            button = ctk.CTkButton(settings, text=text, command=action, state='disabled' if self.ai_busy else 'normal')
            button.pack(anchor='w', padx=16, pady=5)
            self.ai_buttons.append(button)
        self.ai_status = app.label(settings, 'Model analysis is optional; deterministic results are always available.', size=12)
        self.ai_evidence = ctk.CTkButton(settings, text='Model-linked evidence', state='disabled')
        self.ai_evidence.pack(anchor='w', padx=16, pady=6)
        if self.ai_view == app.view_generation and self.ai_result:
            self._show_ai_result(self.ai_result)

    def _lan_warning(self):
        self.warning.configure(text=LAN_WARNING if self.lan.get() else 'Only 127.0.0.1, localhost or ::1 model endpoints are allowed.')

    def save_config(self):
        try:
            config = AIConfig(enabled=self.enabled.get(), base_url=self.endpoint.get().strip(),
                              model=self.model.get().strip(), allow_lan_model=self.lan.get(),
                              timeout_seconds=self.config.timeout_seconds, max_tokens=self.config.max_tokens)
            self.store.save(config)
            self.config = config
        except (OSError, ValueError, TypeError) as exc:
            self.ai_status.configure(text=f'Model settings were not saved: {exc}')
            return None
        self.ai_status.configure(text='Model settings saved. ' + (config.warning or 'No request was made.'))
        return config

    def run_ai(self, generate):
        if self.ai_busy or self.app.closing:
            return
        config = self.save_config()
        if config is None:
            return
        self.ai_busy = True
        for button in self.ai_buttons:
            button.configure(state='disabled')
        self.ai_status.configure(text='Generating model interpretation...' if generate else 'Checking model connection...')
        view = self.app.view_generation
        profile = self.app.result.get('behavioral') or analyze_behavior(self.app.result.get('records', []))

        def worker():
            try:
                provider = ColibriProvider(config)
                result = provider.generate(profile) if generate else {'status': 'CONNECTION', 'detail': provider.health().detail}
            except Exception:
                result = {'status': 'ERROR', 'detail': 'The optional model request failed. Deterministic analysis remains available.'}
            self.app.dispatch(self._ai_complete, view, result)

        threading.Thread(target=worker, name='nexdata-local-ai', daemon=True).start()

    def _ai_complete(self, view, result):
        self.ai_busy = False
        if self.app.closing:
            return
        # A result belongs only to the evidence snapshot that generated it.
        if view == self.app.view_generation:
            self.ai_result, self.ai_view = result, view
            self._show_ai_result(result)
        for button in self.ai_buttons:
            if button.winfo_exists():
                button.configure(state='normal')

    def _show_ai_result(self, result):
        lines = [result.get('detail') or result.get('summary', '')]
        if result.get('status') == 'COMPLETED':
            lines.insert(0, 'Model-generated interpretation; verify every claim against the deterministic evidence.')
            for key in ('observations', 'relationships', 'hypotheses'):
                lines += [f"{key.title()}: {r['text']}" for r in result.get(key, [])]
            lines += result.get('limitations', [])
            if result.get('invalidEvidenceIds'):
                lines.append('The model cited unknown evidence; those references were discarded.')
        self.ai_status.configure(text='\n'.join(lines))
        ids = list(dict.fromkeys(result.get('evidence_ids', []) + [rid for key in ('observations', 'relationships', 'hypotheses')
                           for row in result.get(key, []) for rid in row.get('evidence_ids', [])]))
        self.ai_evidence.configure(state='normal' if ids else 'disabled',
            command=lambda: self.app.show_evidence({'title': 'Model-linked evidence; verify the interpretation', 'evidence': ids}))

    def render_photos(self):
        app = self.app
        page = app.scroll_page('Photos')
        app.label(page, 'Photos: local privacy checks', bold=True, size=20)
        app.label(page, 'Select only images you want NexData to retain and examine locally. Copies stay in .cache/image-exposure until Clear images. Original files are never changed. No upload or public search.')
        ctk.CTkButton(page, text='Add images', command=self.add_images).pack(anchor='w', padx=16, pady=6)
        ctk.CTkButton(page, text='Clear images', command=lambda: self.photo_job(clear=True)).pack(anchor='w', padx=16, pady=6)
        photos = app.result.get('photos') or {}
        app.label(page, photos.get('limitations', 'No selected photos have been analyzed.'), size=12)
        app.label(page, 'SHA-256 detects identical bytes; perceptual hashes only suggest visual similarity. OCR retains pattern flags, not recognized text.', size=12)
        summary = photos.get('summary') or {}
        app.label(page, ' | '.join(f'{key}: {value}' for key, value in summary.items()), size=12)

        def image(parent, row):
            card = app.card(parent)
            app.label(card, row['name'], bold=True)
            meta = row['metadata']
            app.label(card, 'GPS: ' + ('present' if 'latitude' in meta else 'not found') +
                      ' | OCR: ' + ('checked' if row['ocr_available'] else 'not checked / unavailable'), size=12)
            app.label(card, 'Pattern flags: ' + (', '.join(row['sensitive_text']) or 'none detected'), size=12)
            ctk.CTkButton(card, text='Photo evidence', command=lambda: app.show_evidence({'title': row['name'], 'evidence': [row['id']]})).pack(anchor='w', padx=16, pady=8)

        paged_items(page, photos.get('images', []), image)
        for finding in photos.get('findings', []):
            app.label(page, finding['title'], bold=True)
        app.label(page, 'Photo findings also appear in Findings, Fix first and saved reports.', size=12)

    def add_images(self):
        if self.app.loading or self.app.closing:
            return
        paths = filedialog.askopenfilenames(parent=self.app, title='Add photos for local privacy checks',
                                            filetypes=[('Photos', '*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff')])
        if paths:
            self.photo_job(paths=paths)

    def photo_job(self, *, paths=(), clear=False):
        app = self.app
        if app.loading or app.closing:
            return
        app.loading = True
        app.cancel_event = threading.Event()
        event = app.cancel_event
        snapshot = app.result
        app.pending_paths = list(app.loaded_paths)
        for button in (app.open_button, app.scan_button, app.resolve_button, app.scan_mode):
            button.configure(state='disabled')
        app.cancel_button.configure(state='normal')
        app.cancel_button.grid()
        app.progress.grid()
        app.progress.start()
        app.status_label.configure(text='Clearing retained images...' if clear else 'Checking selected photos locally...')

        def worker():
            try:
                from .main import prepare_charts
                with cancellation(event):
                    if clear:
                        self.images.clear_images()
                    else:
                        self.images.add(paths)
                    photos = scan_exposure(self.images, use_ocr=True)
                    result = merge_photo_result(snapshot, photos)
                    charts = prepare_charts(result)
            except Cancelled:
                app.dispatch(app.load_cancelled)
            except Exception as exc:
                app.dispatch(app.load_failed, f'Photo check failed: {exc}')
            else:
                app.dispatch(app.load_complete, result, charts, len(app.loaded_paths))

        threading.Thread(target=worker, name='nexdata-photos', daemon=True).start()
