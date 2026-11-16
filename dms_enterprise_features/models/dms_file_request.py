# Copyright 2026 Hudson Community
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).
"""Links and file requests on dms.file (like Odoo Documents "Link" / "Request").

A dms.file is one of three kinds:

* ``binary``  – a normal uploaded file (default, all existing records)
* ``url``     – a link; the card shows the page's Open Graph image and title
* ``request`` – a placeholder for a missing file that someone was asked to
  upload. The requestee gets an email with an upload link (public page,
  access-token protected) and, when they are an internal user, an "upload"
  activity and access to the placeholder so they can upload from the backend.
"""
import base64
import logging
import mimetypes
import os
import re
import secrets
from urllib.parse import parse_qs, urlparse

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.dms.tools import file as dms_file_tools

_logger = logging.getLogger(__name__)

_INVALID_NAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
_YOUTUBE_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?.*v=|embed/|shorts/|v/)|youtu\.be/)([A-Za-z0-9_-]{6,})"
)


def _clean_file_name(name, fallback="Link"):
    name = _INVALID_NAME_CHARS.sub("-", (name or "").strip())
    name = re.sub(r"\s+", " ", name).strip(" .-")
    return (name or fallback)[:200]


def _youtube_id(url):
    match = _YOUTUBE_RE.search(url or "")
    if match:
        return match.group(1)
    parsed = urlparse(url or "")
    if parsed.netloc.endswith("youtube.com"):
        return (parse_qs(parsed.query).get("v") or [False])[0]
    return False


class DMSFile(models.Model):
    _inherit = "dms.file"

    file_kind = fields.Selection(
        selection=[
            ("binary", "File"),
            ("url", "Link"),
            ("request", "Requested File"),
        ],
        string="Kind",
        default="binary",
        required=True,
        index=True,
    )
    url = fields.Char(string="URL")
    url_preview_image = fields.Char(
        string="URL Preview Image",
        help="Image published by the linked page (Open Graph og:image), "
             "or the YouTube thumbnail for YouTube links.",
    )
    url_thumbnail = fields.Image(
        string="URL Thumbnail",
        max_width=512,
        max_height=512,
        attachment=True,
        help="Copy of the preview image, so the card does not depend on the "
             "linked site allowing its images to be embedded.",
    )
    url_domain = fields.Char(compute="_compute_url_domain")

    request_partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Requested To",
        index=True,
    )
    requested_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Requested By",
    )
    request_date_deadline = fields.Date(string="Request Due Date")
    request_message = fields.Text(string="Request Message")
    request_token = fields.Char(copy=False, readonly=True)
    request_upload_url = fields.Char(compute="_compute_request_upload_url")
    can_upload_request = fields.Boolean(compute="_compute_can_upload_request")

    @api.depends("file_kind")
    def _compute_extension(self):
        # A link named "youtube.com" or a request named "Report v1.2" is not a
        # file with an extension; the extension rules apply once a requested
        # file is actually uploaded (the kind then becomes "binary").
        files = self.filtered(lambda r: r.file_kind in (False, "binary"))
        super(DMSFile, files)._compute_extension()
        (self - files).extension = False

    @api.depends("url")
    def _compute_url_domain(self):
        for record in self:
            record.url_domain = urlparse(record.url or "").netloc.removeprefix("www.") if record.url else False

    def _compute_request_upload_url(self):
        base_url = self.get_base_url() if self else ""
        dbname = self.env.cr.dbname
        for record in self:
            if record.file_kind != "request" or not record.id:
                record.request_upload_url = False
                continue
            token = record.sudo()._dms_request_ensure_token()
            record.request_upload_url = (
                f"{base_url.rstrip('/')}/dms/request/{record.id}"
                f"?token={token}&db={dbname}"
            )

    def _dms_request_ensure_token(self):
        """Own token for the upload link: the file's portal access_token would
        also open the download routes once the file has been provided."""
        self.ensure_one()
        if not self.request_token:
            self.sudo().write({"request_token": secrets.token_urlsafe(24)})
        return self.request_token

    @api.depends_context("uid")
    @api.depends("file_kind", "request_partner_id", "requested_by_id")
    def _compute_can_upload_request(self):
        for record in self:
            record.can_upload_request = bool(record.id) and record._dms_can_fulfill_request(self.env.user)

    # ------------------------------------------------------------------
    # Links
    # ------------------------------------------------------------------

    @api.model
    def _dms_normalize_url(self, url):
        url = (url or "").strip()
        if not url:
            raise UserError(_("Please enter a URL."))
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
            url = "https://" + url
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise UserError(_("Please enter a valid web address (http:// or https://)."))
        return url

    @api.model
    def _dms_fetch_link_preview(self, url):
        """Return {'title': str|False, 'image': str|False} for ``url``.

        Uses Odoo's own Open Graph reader (the same one Discuss uses for link
        previews). Never raises: an unreachable site just gives no preview.
        """
        result = {"title": False, "image": False}
        yt_id = _youtube_id(url)
        if yt_id:
            result["image"] = f"https://img.youtube.com/vi/{yt_id}/hqdefault.jpg"
        if self.env.context.get("dms_skip_link_preview"):
            return result
        try:
            from odoo.addons.mail.tools.link_preview import get_link_preview_from_url

            preview = get_link_preview_from_url(url) or {}
        except Exception:  # noqa: BLE001 - a preview is best effort only
            _logger.info("DMS link preview failed for %s", url, exc_info=True)
            preview = {}
        title = preview.get("og_title")
        if title:
            result["title"] = " ".join(str(title).split())
        image = preview.get("og_image")
        if image and not result["image"]:
            image = str(image).strip()
            if image.startswith("//"):
                image = "https:" + image
            elif image.startswith("/"):
                parsed = urlparse(preview.get("source_url") or url)
                image = f"{parsed.scheme}://{parsed.netloc}{image}"
            if image.startswith(("http://", "https://")):
                result["image"] = image
        return result

    @api.model
    def _dms_download_preview_image(self, image_url):
        """Base64 of the preview image (str), or False. Best effort."""
        if not image_url or self.env.context.get("dms_skip_link_preview"):
            return False
        try:
            import requests

            from odoo.tools.image import image_process

            response = requests.get(
                image_url,
                timeout=4,
                stream=True,
                # same identification as Odoo's link previewer; some sites
                # stall image requests without a browser-like Accept header
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:91.0) Gecko/20100101 Firefox/91.0",
                    "Accept": "image/avif,image/webp,image/png,image/*;q=0.8,*/*;q=0.5",
                    "Odoo-Link-Preview": "True",
                },
            )
            if not response.ok or not (response.headers.get("Content-Type") or "").startswith("image/"):
                return False
            data = b""
            for chunk in response.iter_content(65536):
                data += chunk
                if len(data) > 5 * 1024 * 1024:
                    return False
            data = image_process(data, size=(512, 512))
            return base64.b64encode(data).decode() if data else False
        except Exception:  # noqa: BLE001 - unreadable image: keep the link icon
            _logger.info("DMS link preview image download failed for %s", image_url, exc_info=True)
            return False

    @api.model
    def _dms_unique_name_in(self, directory, name):
        names = directory.sudo().file_ids.mapped("name")
        if name not in names:
            return name
        return dms_file_tools.unique_name(name, names)

    @api.model
    def dms_create_link(self, directory_id, url, name=False):
        """Create a link document in ``directory_id``; returns the new record."""
        url = self._dms_normalize_url(url)
        directory = self.env["dms.directory"].browse(directory_id).exists()
        if not directory:
            raise UserError(_("Please select a folder first."))
        preview = self._dms_fetch_link_preview(url)
        clean = _clean_file_name(name or preview["title"] or urlparse(url).netloc, fallback=_("Link"))
        return self.create({
            "name": self._dms_unique_name_in(directory, clean),
            "directory_id": directory.id,
            "file_kind": "url",
            "url": url,
            "url_preview_image": preview["image"],
            "url_thumbnail": self._dms_download_preview_image(preview["image"]),
        })

    def action_dms_open_url(self):
        self.ensure_one()
        if self.file_kind != "url" or not self.url:
            raise UserError(_("This document is not a link."))
        return {"type": "ir.actions.act_url", "url": self.url, "target": "new"}

    # ------------------------------------------------------------------
    # Requests
    # ------------------------------------------------------------------

    @api.model
    def dms_create_request(self, vals):
        """Create a file request and notify the requestee.

        ``vals``: name, directory_id, partner_id, date_deadline, message,
        tag_ids (list of ids).
        """
        partner = self.env["res.partner"].browse(vals.get("partner_id")).exists()
        if not partner:
            raise UserError(_("Please choose who you request the file from."))
        if not partner.email:
            raise UserError(_("%s has no email address, so the request cannot be sent.", partner.display_name))
        directory = self.env["dms.directory"].browse(vals.get("directory_id")).exists()
        if not directory:
            raise UserError(_("Please select a folder first."))
        name = _clean_file_name(vals.get("name"), fallback=_("Requested Document"))

        record = self.create({
            "name": self._dms_unique_name_in(directory, name),
            "directory_id": directory.id,
            "file_kind": "request",
            "request_partner_id": partner.id,
            "requested_by_id": self.env.uid,
            "request_date_deadline": vals.get("date_deadline") or False,
            "request_message": vals.get("message") or False,
            "tag_ids": [(6, 0, vals.get("tag_ids") or [])],
        })
        record._dms_request_ensure_token()
        record._dms_request_grant_access()
        record._dms_request_schedule_activity()
        record._dms_request_send_email()
        return record

    def _dms_request_users(self):
        """Internal users behind the requested partner."""
        self.ensure_one()
        return self.request_partner_id.sudo().user_ids.filtered(
            lambda u: u.active and u._is_internal()
        )

    def _dms_request_grant_access(self):
        """Let the requestee see the placeholder and upload into it."""
        for record in self.sudo():
            partner = record.request_partner_id
            if not partner or not partner.user_ids:
                continue  # external contact: the token link is enough
            if record.access_ids.filtered(lambda a: a.partner_id == partner):
                continue
            self.env["dms.file.access"].sudo()._ensure_user_for_partner(partner)
            self.env["dms.file.access"].sudo().create({
                "file_id": record.id,
                "partner_id": partner.id,
                "perm_view": True,
                "perm_download": True,
                "perm_edit": True,
            })

    def _dms_request_schedule_activity(self):
        activity_type = self.env.ref("mail.mail_activity_data_upload_document", raise_if_not_found=False)
        if not activity_type:
            return
        for record in self:
            user = record._dms_request_users()[:1]
            if not user:
                continue
            note = Markup("<p>%s</p>") % (record.request_message or _("Please upload the requested document."))
            # the request email already tells them: no second "assigned to you" mail
            record.sudo().with_context(mail_activity_quick_update=True).activity_schedule(
                act_type_xmlid="mail.mail_activity_data_upload_document",
                date_deadline=record.request_date_deadline or fields.Date.context_today(record),
                summary=_("Upload: %s", record.name),
                note=note,
                user_id=user.id,
            )

    def _dms_request_send_email(self):
        template = self.env.ref("dms_enterprise_features.mail_template_dms_file_request", raise_if_not_found=False)
        if not template:
            return
        for record in self:
            tpl = template.sudo()
            body = tpl._render_field("body_html", record.ids, compute_lang=True)[record.id]
            subject = tpl._render_field("subject", record.ids, compute_lang=True)[record.id]
            email_from = tpl._render_field("email_from", record.ids)[record.id]
            requester = record.requested_by_id or self.env.user
            # an explicitly addressed partner is emailed even on a note, so the
            # requester's followers are not spammed with a copy
            post_values = {}
            email_from = (email_from or "").strip() or (requester.email and requester.email_formatted)
            if email_from:
                # otherwise let message_post pick its default sender
                post_values["email_from"] = email_from
            record.with_context(mail_notify_force_send=False).message_post(
                **post_values,
                body=body,
                subject=subject,
                author_id=requester.partner_id.id,
                partner_ids=record.request_partner_id.ids,
                message_type="comment",
                subtype_xmlid="mail.mt_note",
                email_layout_xmlid="dms_enterprise_features.mail_notification_dms_request",
                mail_auto_delete=True,
            )

    def _dms_can_fulfill_request(self, user):
        self.ensure_one()
        if self.file_kind != "request" or user._is_public():
            return False
        rec = self.sudo()
        if user.partner_id == rec.request_partner_id or user == rec.requested_by_id:
            return True
        return bool(rec._dms_effective_permissions(user).get("edit"))

    def action_dms_request_upload(self, filename, data):
        """Upload the requested file from the backend (base64 ``data``)."""
        self.ensure_one()
        if not self._dms_can_fulfill_request(self.env.user):
            raise AccessError(_("You are not allowed to upload the file for this request."))
        if not data:
            raise UserError(_("The file is empty."))
        self.sudo()._dms_fulfill_request(filename, data, self.env.user.partner_id)
        return True

    def _dms_fulfill_request(self, filename, data_b64, uploader_partner=False):
        """Turn the request placeholder into a real file. Call with sudo."""
        self.ensure_one()
        if self.file_kind != "request":
            raise UserError(_("This document has already been provided."))
        if isinstance(data_b64, bytes):
            data_b64 = data_b64.decode()

        ext = os.path.splitext(filename or "")[1].lower()
        if not ext:
            raw = base64.b64decode(data_b64)
            from odoo.tools.mimetypes import guess_mimetype

            ext = mimetypes.guess_extension(guess_mimetype(raw)) or ""
        name = self.name
        if ext and not name.lower().endswith(ext):
            name = f"{name}{ext}"
        if name != self.name:
            others = self.directory_id.file_ids.filtered(lambda f: f.id != self.id).mapped("name")
            if name in others:
                name = dms_file_tools.unique_name(name, others, escape_suffix=True)

        requester = self.requested_by_id
        # first content of the document: one 1.0 revision (a plain write would
        # add an "Initial version" plus a 1.1 replacement of the same file)
        self.with_context(no_new_revision=True).write({
            "name": name,
            "content": data_b64,
            "file_kind": "binary",
        })
        if not self.revision_ids:
            uploader = self.env.user if not self.env.user._is_public() else (requester or self.create_uid)
            rev = self.env["dms.file.revision"].sudo().create({
                "file_id": self.id,
                "version": "1.0",
                "content": self.content,
                "file_name": self.name,
                "uploader_id": uploader.id if uploader else False,
                "upload_date": fields.Datetime.now(),
                "comments": _("Requested document provided"),
                "is_current": True,
            })
            self.with_context(from_revert_revision=True, dms_skip_log=True).write({"current_revision_id": rev.id})
        upload_activities = self.activity_ids.filtered(
            lambda a: a.activity_type_id == self.env.ref("mail.mail_activity_data_upload_document", raise_if_not_found=False)
        )
        if upload_activities:
            upload_activities.action_feedback(feedback=_("Document uploaded"))

        who = uploader_partner.display_name if uploader_partner else (self.request_partner_id.display_name or _("Someone"))
        self.with_context(mail_notify_force_send=False).message_post(
            body=Markup("<p>%s</p>") % _("%(who)s provided the requested document %(name)s.", who=who, name=self.name),
            partner_ids=requester.partner_id.ids if requester else [],
            subtype_xmlid="mail.mt_note",
            author_id=uploader_partner.id if uploader_partner else self.request_partner_id.id,
        )
        return True

    def action_dms_request_resend(self):
        for record in self:
            if record.file_kind == "request":
                record._dms_request_send_email()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"type": "success", "message": _("The request was sent again.")},
        }
