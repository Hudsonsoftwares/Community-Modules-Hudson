# Copyright 2026 Hudson Community
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).
"""Public page where a requested person uploads the missing document."""
import base64

from odoo import _, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request
from odoo.tools import consteq


class DmsFileRequestController(http.Controller):

    def _dms_request_record(self, file_id, token):
        record = request.env["dms.file"].sudo().browse(file_id).exists()
        if (
            not record
            or not token
            or not record.request_token
            or not consteq(record.request_token, token)
        ):
            return None
        return record

    def _dms_request_render(self, record, token, **values):
        company = record.company_id or request.env.company
        return request.render("dms_enterprise_features.portal_file_request_page", {
            "file": record,
            "token": token,
            "company": company,
            "requester": record.requested_by_id,
            "is_open": record.file_kind == "request" and record.active and not record.is_trashed,
            "csrf_token": request.csrf_token(),
            "db_name": request.env.cr.dbname,
            **values,
        })

    @http.route("/dms/request/<int:file_id>", type="http", auth="public", methods=["GET"])
    def dms_request_page(self, file_id, token=None, **kw):
        record = self._dms_request_record(file_id, token)
        if not record:
            return request.not_found()
        return self._dms_request_render(record, token, success=kw.get("success") == "1")

    @http.route("/dms/request/<int:file_id>/upload", type="http", auth="public", methods=["POST"], csrf=True)
    def dms_request_upload(self, file_id, token=None, **post):
        record = self._dms_request_record(file_id, token)
        if not record:
            return request.not_found()
        if record.file_kind != "request" or not record.active or record.is_trashed:
            return self._dms_request_render(record, token)

        upload = post.get("ufile")
        data = upload.read() if upload else b""
        if not data:
            return self._dms_request_render(record, token, error=_("Please choose a file to upload."))

        user = request.env.user
        uploader = record.request_partner_id if user._is_public() else user.partner_id
        try:
            record._dms_fulfill_request(
                upload.filename,
                base64.b64encode(data).decode(),
                uploader,
            )
        except (UserError, ValidationError) as exc:
            request.env.cr.rollback()
            return self._dms_request_render(record, token, error=exc.args[0] if exc.args else str(exc))
        return request.redirect(f"/dms/request/{record.id}?token={token}&success=1&db={request.env.cr.dbname}")
