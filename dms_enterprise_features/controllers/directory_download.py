import io
import zipfile
import base64
from odoo import http, _
from odoo.http import request
from odoo.http.stream import content_disposition
from odoo.exceptions import AccessError

class DmsDirectoryDownloadController(http.Controller):

    @http.route('/dms/directory/<int:directory_id>/download_zip', type='http', auth='user')
    def download_directory_zip(self, directory_id, **kw):
        directory = request.env['dms.directory'].browse(directory_id)
        if not directory.exists():
            return request.not_found()

        # Check download permission
        if not directory.permission_download and not request.env.user.has_group('dms.group_dms_manager') and not request.env.user.has_group('base.group_system'):
            raise AccessError(_("You do not have permission to download files from this directory."))

        # Search all permitted files in this directory and its subdirectories
        files = request.env['dms.file'].search([('directory_id', 'child_of', directory.id)])
        
        # Build in-memory zip
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for f in files:
                # Check file-level download permission
                if not f.permission_download and not request.env.user.has_group('dms.group_dms_manager') and not request.env.user.has_group('base.group_system'):
                    continue
                
                # Determine relative path inside zip
                rel_path_parts = []
                curr_dir = f.directory_id
                while curr_dir and curr_dir.id != directory.id:
                    rel_path_parts.insert(0, curr_dir.name)
                    curr_dir = curr_dir.parent_id
                
                rel_path_parts.append(f.name)
                archive_name = "/".join(rel_path_parts)
                
                try:
                    file_data = base64.b64decode(f.content) if f.content else b""
                    zip_file.writestr(archive_name, file_data)
                except Exception:
                    pass

        zip_buffer.seek(0)
        zip_data = zip_buffer.read()
        filename = f"{directory.name}.zip"

        return request.make_response(
            zip_data,
            headers=[
                ('Content-Type', 'application/zip'),
                ('Content-Disposition', content_disposition(filename)),
            ]
        )
