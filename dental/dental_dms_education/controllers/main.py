# -*- coding: utf-8 -*-
import json

from werkzeug.exceptions import Forbidden, NotFound

from odoo import http
from odoo.exceptions import AccessError, MissingError
from odoo.http import request

NO_STORE = [('Cache-Control', 'no-store'), ('X-Robots-Tag', 'noindex, nofollow'), ('Referrer-Policy', 'no-referrer')]


class DentalEducationController(http.Controller):

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _media_payload(media, url, thumb_url=None):
        return {
            'id': media.id,
            'name': (media.name or '').rsplit('.', 1)[0],
            'kind': media._dental_edu_kind(),
            'lang': media.dental_edu_lang_id.name or '',
            'lang_code': media.dental_edu_lang_id.code or '',
            'url': url,
            'thumb': thumb_url,
            'description': media.dental_edu_description or '',
            'duration': media.dental_edu_duration or '',
        }

    @staticmethod
    def _stream_response(media):
        stream = media._dental_edu_stream()
        response = stream.get_response(as_attachment=False, content_security_policy=None)
        for header, value in NO_STORE:
            response.headers[header] = value
        return response

    @staticmethod
    def _readable_education_media(file_id):
        """Education media the current user may read.

        Uses a search (which applies the DMS folder permissions as SQL): the DMS security mixin makes
        per-record checks (check_access / has_access) succeed for any dms.file.
        """
        media = request.env['dms.file'].search([('id', '=', file_id), ('dental_doc_type', '=', 'education')], limit=1)
        if not media:
            raise NotFound()
        try:
            media.check_access('read')
        except AccessError:
            raise Forbidden()
        return media

    # ------------------------------------------------------------------ dentist preview (logged-in users)
    @http.route('/dental/education/preview/<int:file_id>', type='http', auth='user', methods=['GET'])
    def preview(self, file_id, **kwargs):
        media = self._readable_education_media(file_id)
        family = media.sudo()._dental_edu_family()
        items = [self._media_payload(m, f'/dental/education/media/{m.id}') for m in family]
        values = {
            'title': media.sudo().name,
            'patient_label': False,
            'data_json': json.dumps({'mode': 'preview', 'items': [{
                'line_id': False, 'topic': media.sudo().category_id.name or '',
                'versions': items, 'current': media.id}]}),
        }
        return request.render('dental_dms_education.education_presenter', values, headers=NO_STORE)

    @http.route('/dental/education/media/<int:file_id>', type='http', auth='user', methods=['GET'])
    def media(self, file_id, **kwargs):
        media = self._readable_education_media(file_id)
        return self._stream_response(media)

    # ------------------------------------------------------------------ clinic monitor / tablet (token)
    def _session(self, session_id, token):
        session = request.env['dental.education.session'].sudo()._get_by_token(session_id, token)
        if not session:
            raise NotFound()
        return session

    @http.route('/dental/education/present/<int:session_id>/<string:token>', type='http', auth='public',
                methods=['GET'], sitemap=False)
    def present(self, session_id, token, device=None, **kwargs):
        session = self._session(session_id, token)
        lang = session.lang_id.code or session.patient_id.lang or 'en_US'
        base = f'/dental/education/present/{session.id}/{token}'
        items = []
        for line in session.line_ids:
            family = line.file_id._dental_edu_family().filtered('dental_edu_published')
            if not family:
                continue
            items.append({
                'line_id': line.id,
                'topic': line.file_id.category_id.with_context(lang=lang).name or '',
                'current': line.play_file_id.id,
                'completed': line.completed,
                'versions': [self._media_payload(
                    m, f'{base}/media/{line.id}/{m.id}',
                    f'{base}/thumb/{line.id}/{m.id}' if m.image_1920 else None) for m in family],
            })
        # Patient privacy on a shared screen: first name only.
        first_name = (session.patient_id.name or '').split(' ')[0]
        values = {
            'title': session.with_context(lang=lang).name,
            'patient_label': first_name,
            'data_json': json.dumps({
                'mode': 'present', 'items': items, 'event_url': f'{base}/event',
                'device': device if device in ('screen', 'tablet', 'desktop') else 'screen',
                'acknowledged': session.acknowledged,
            }),
        }
        html = request.env['ir.ui.view'].with_context(lang=lang)._render_template(
            'dental_dms_education.education_presenter', values)
        return request.make_response(html, headers=[('Content-Type', 'text/html; charset=utf-8')] + NO_STORE)

    def _line_media(self, session, line_id, file_id):
        line = session.line_ids.filtered(lambda l: l.id == line_id)
        if not line:
            raise NotFound()
        media = line.file_id._dental_edu_family().filtered(lambda m: m.id == file_id and m.dental_edu_published)
        if not media:
            raise NotFound()
        return line, media

    @http.route('/dental/education/present/<int:session_id>/<string:token>/media/<int:line_id>/<int:file_id>',
                type='http', auth='public', methods=['GET'], sitemap=False)
    def present_media(self, session_id, token, line_id, file_id, **kwargs):
        session = self._session(session_id, token)
        _line, media = self._line_media(session, line_id, file_id)
        try:
            return self._stream_response(media)
        except MissingError:
            raise NotFound()

    @http.route('/dental/education/present/<int:session_id>/<string:token>/thumb/<int:line_id>/<int:file_id>',
                type='http', auth='public', methods=['GET'], sitemap=False)
    def present_thumb(self, session_id, token, line_id, file_id, **kwargs):
        session = self._session(session_id, token)
        _line, media = self._line_media(session, line_id, file_id)
        stream = request.env['ir.binary']._get_image_stream_from(media.sudo(), 'image_1920', width=480, height=270,
                                                                crop=True)
        return stream.get_response(as_attachment=False)

    @http.route('/dental/education/present/<int:session_id>/<string:token>/event', type='jsonrpc', auth='public',
                methods=['POST'], sitemap=False)
    def present_event(self, session_id, token, event=None, line_id=None, file_id=None, position=0, duration=0,
                      view_id=None, device=None, note=None, **kwargs):
        session = self._session(session_id, token)
        if event not in ('start', 'progress', 'complete', 'ack'):
            return {'ok': False}
        line = variant = False
        if event != 'ack':
            line, variant = self._line_media(session, int(line_id or 0), int(file_id or 0))
        return session._register_event(line, event, position=position, duration=duration, view_id=view_id,
                                       device=device, variant=variant, note=note)
